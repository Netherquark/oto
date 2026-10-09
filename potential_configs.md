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
| ~~**C8**~~ | ZZ VW2 probe | ZZ | 64x64x8 | 4x4 | 2 | 2 | 8 | 4 | 1 | 0/0 | **WITHDRAWN — illegal, not a candidate.** Listed here as "cap 2 / PASS" on the strength of `cap_vector_width()`, which read `ZZ: 8` bytes/element. Complex double is **16** B, so `VW=2` demands a 32 B global load against a 16 B cap and Tensile refuses the kernel (`GlobalLoadVectorWidthA * DataType.numBytes() > 16`). 28 archived phases carried this config and one overnight run was spent rediscovering it. The widest legal ZZ width is **VW=1** | **FAIL** (see `gfx90c_theoretical_limits.md` §1) |
| **C9** | SS 256 | SS | 32x64x8 | **4x8** | **4** | 4 | 8 | 4 | 1 | 0/0 | floor winner on SS:256. **Anisotropic** tile; no quantisation argument proposes it, and it was never generated. Note SS:256 is already a WIN (+226.9%) — this candidate targets utilisation (25.5% of roof), not conversion | **PASS** |
| **C10** | HH 256 | HH | **64x32**x16 | 4x4 | **4** | 4 | 16 | 4 | 1 | 0/0 | floor winner on HH:256. 128 threads vs 64 for 64x64 — an axis the quantisation ladder cannot see. Never generated. Already a WIN (+270.8%); targets 23.7% of roof | **PASS** |
| **C11** | ZZ 192 | ZZ | 32x32x8 | **4x4** | 1 | 1 | 8 | 4 | 1 | 0/0 | floor winner on ZZ:192. 4x4 complex double is TT0*TT1*8 = 128 accumulator VGPRs, exactly on budget. Already a WIN (+37.5%); targets 20.4% of roof | **PASS** |
| **C12** | ZZ 128 | ZZ | **64x64x16** | 4x4 | 1 | 1 | 16 | 4 | 1 | 0/0 | floor winner on ZZ:128. Already a WIN (+203.7%); targets 16.7% of roof, the worst-utilised cell in the corpus | **PASS** |
| **C13** | ZZ 512 | ZZ | 64x64x8 | 4x4 | 1 | 1 | 8 | 4 | 1 | 0/**1** | floor winner on ZZ:512 is C12's tile at DU8 plus `LdsPadB 1` — the only ZZ pad with measured support. Already a WIN (+8.3%), the thinnest margin of the six; targets 22.6% of roof | **PASS** |

`GLVW = VectorWidth` throughout: the stock `GLVW == VW or GLVW == 1` generator
restriction is satisfied without weakening it, so none of C1–C7 needs the
guard-relaxation route that HS_HPA required. C8 is withdrawn (illegal VW2 for
complex double) rather than re-scoped.

## 3.0 What actually ships: the consolidated deck (2026-10-03)

C1–C13 above are *proposals*. The deck that is actually on disk is different and
much smaller, because it was selected by measurement rather than by argument.
`consolidate.py` picks, per target cell, the **best measured** existing phase and
the **widest existing** phase matching the floor's invocation form, then emits the
union. Current result:

- **29 phases, covering 38/38 target cells**, dtype mix `H`11 / `D`5 / `S`5 /
  `C`4 / `Z`4. Every entry has 4–8 shapes, i.e. every shipped phase is a
  **multi-shape sweep** — the single-shape form that made the last run
  ungradable is gone from the deck entirely.
- Every entry is a **verbatim copy** of a phase in
  `archive/phases.yaml.pre_consolidation_oct3`. Nothing was generated, re-keyed,
  or invented; the deck is a selection, not a design.
- Every cell's **best measured solution is retained**, including the six current
  losses (`HH:1024/2048/4096`, `SS:768/1024/2048`). Verified cell-by-cell
  against the mining record: 38/38 present, 0 missing.
- 28 candidate phases are **dropped as illegal** before selection.

Because selection draws from the union of all archived decks (1644 solutions ever
written) rather than the live deck, re-running reproduces the same 29 — see
`changelog.md` 2026-10-03 for why the earlier 45-phase deck was not a fixpoint.

The C1–C13 proposals remain the *next* step; they are deliberately not folded
into the deck, because doing so would mean shipping unmeasured configs and the
user's constraint is to retain measured solutions, not invent new ones.

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
---

## 8. Mutation/auto-run findings (2026-10-07) — why iteration "broke", and the real remaining gap

Everything below is derived from the run corpus (`run_20260920_235815`
… `run_20261006_122020` + the locked floor), re-parsed directly from each
phase's own `00_Final.yaml` (DataType enum) and `00_Final.csv` (per-seed
GFlops), cross-checked against `registry.db` and `acceptance_report.json`.
No GPU was used; all legality checks are CPU-only.

### 8.1 Why the last iteration stage looked broken

`run_20261006_122020` (auto + mutation arm, 12:20→22:06, status `completed`)
proposed **506** candidates: **329 functional, 97 legal_rejected, 59
legal_slow, 21 pending**.

- The ledger's last row is `phase_auto_8_*` at 22:05:59. Iteration 9 then
  emitted 23 proposals (**2 legal_rejected + 21 accepted**) into the overlay
  and the run ended *without benchmarking them*. The overlay therefore holds 21
  **never-measured** phases — the arm stopped after writing its final
  generation (`phases_executed: 18`, `phases_skipped: 29`).
- The overlay carries **only iteration 9**. Every benchmarked winner from
  iterations 0–8 exists as a phase dir + CSV but is **not** in `phases.yaml`
  (29-phase deck) nor in any overlay, so a resumed/fresh auto run would never
  re-benchmark them. That is the "existing / explored / proven winners aren't
  in use" observation — quantified in §8.4.
- 97 legal_rejected (19%) and the 21-pending cap are the sampler faults this
  week's fix removes: the pre-fix generator proposed configs `validate_config`
  would never accept (GLVW≠VW divisibility, 24,576-B LDS footprints, half
  `GlobalSplitU` assembly classes). The new co-occurrence gate
  (`legality.cooccurrence_check`, DepthU folded into the tile group) raised the
  sweep's legal rate from 88% to 100% and prunes ~9% of draws — measured
  CPU-only, all 7 families still propose.

**The loop itself was never the bottleneck — it is captured by its own
convergence test.** `agent.converged` (agent.py:126) requires **no below-ceiling
cells** plus ≥3 configs/cell, ≥6 seeds/cell, CV ≤15%. SS sits at ~1–10% of the
1613 ceiling and CC at ~20–28%, so `below_ceiling_cells` is non-empty on every
pass; convergence can never fire and the loop always ends on **"Budget
exhausted"** (iterations = budget) rather than a clean stop. Run 55 made 9
full passes (phase dirs per iteration: 134/62/60/40/25/33/22/21/18, 444 started
/ 417 completed / 27 failed / 261 identical-fp-skipped) and its final pass
over-ran the budget by exactly the 21+2 tail.

**The regression that made the *next* night do nothing is run_20261007_012721
(01:27→01:29, status `skipped`, 0 phase dirs, 0 configs, 0 proposals).** Its
29 `general` records are *all* `status: skipped / reason:
identical_fp_already_passed` — every deck row's fp was already recorded by
run 55's era, so `run_phases` measured nothing. Chain: empty analytics →
`converged([])` returns False ("No analytics data available", never True) →
`harvest({})` yields zero winners → `mutate_and_feed` emits zero candidates →
"No valid mutations generated, stopping" (port_tensile.py:2060). A restart with
nothing new to do is a **silent no-op night**, not a harvest failure. Three
fixes land to make the next overnight run productive regardless:

1. **D1 deck bootstrap** (§8 addendum): 11 provenance rows whose fp has never
   been recorded on a gfx90c registry → guaranteed first-night measurements.
2. **Seed probe bypass**: `run_phases` gates the identical-fp skip for seed
   rows on `overlay_run_id == "seed"` + `has_run_benchmarked(run_id, fp)`, so
   N1–N5 always re-benchmark once per run (fresh variance; also un-blocks the
   mutation arm, which needs analytics to fire).
3. **Spawn the arm from seed analytics**: once probes re-measure, `harvest`
   picks a per-cell winner from *that run's* data and the mutation arm has a
   parent to mutate — the loop can actually run instead of dying at
   mutate-and-feed.

### 8.2 The report's SS verdicts were dtype-polluted

`acceptance_report.json` assigns a phase to a cell from the phase-id family
token, with `FAMILY_TO_DTYPE["auto"]="S"` as fallback. Under the run corpus
that mis-keys two classes of kernel into the **f32 (SS)** cells:

- `phase_auto_2_hh_*` — a **pure f16** kernel (`DataType` enum 4, token `HB`),
  measured 2366–2871 GFlops, physically impossible at the 1613 f32 peak, yet
  the report lists it as the `SS:512/1024/2048/4096` winner.
- `phase_hh_hpa_*` / `phase_hs_hpa_*` — half-input, f32-accumulate kernels
  whose `ComputeDataType` is 0, credited with `SS:1024/2048/4096` "wins" of
  1365–1447 (86–90% of the f32 peak — HPA rate, not SS rate).

Re-splitting every row by its own `00_Final.yaml` DataType and by the
phase-id family token gives the corrected terrain:

| | WIN | TIE | LOSS (dtype-true native vs spoof, >2%) |
|---|---|---|---|
| acceptance report | 16 | 15 | 7 (CC192/256, HH256/1024/2048/4096, SS1365) |
| **dtype-isolated** | 16 | 12 | **10: SS512/768/1000/1365/2048, HH1024/2048, CC256/1024, HS_HPA512** |

The SS large-"wins" were epiphenomena of H/HPA kernels wearing an SS name. The
true SS picture is the opposite: pure-f32 native is 2–7% *below* the spoof at
every shape from 512 up except a 1024 tie. SS:256 is a genuine win (+232%, 98→412
via `auto_0_S`, MT96x96/vw2/du16).

### 8.3 The C1/C2/C5 candidates were measured — and still lose

The Oct-3 headline candidates were configured by **coverage gap**: native had
never run the floor's winning config. The mutation arm then *did* benchmark all
of them. Same source config, both arms, best-median:

| cell | config | native best | floor best | gap |
|---|---|---|---|---|
| SS 768/1000/1365/2048 | `MT128x128x8/8x8/VW4/DU8` | 1046/1030/999/1098 | 1095/1075/1073/1121 | −4…−7% |
| HH 1024/2048 | `MT128x128x16/8x8/VW8/DU16` | 2368/2494 | 2547/2658 | −6…−7% |
| CC 256/1024 | `MT64x64x8/4x4/VW2/DU8` | 188/290 | 214/301 | −12/−4% |

Pooling matched kernel-shape medians across arms (*best*-seed vs *best*-seed is
the report basis; whole-median basis washes most of this out to ~±1%) means the
persistent deficit sits at the **best-seed/tail level**, not in any knob the
deck is missing. It is not coverage: these rows exist. Consequence: **probes
that only widen the same tile no longer target anything**; the load-bearing
move is either (a) the spoof-steal route (§8.6) or (b) shape-specific tile
downsizing (occupancy, §8.5).

### 8.4 Proven winners not in the current 29-phase deck

Every row below is a *measured* all-time-best native kernel that has **no
representative in `phases.yaml`** (+ means beside the deck's current value):

| cell | all-time best (phase) | GFlops | vs deck |
|---|---|---|---|
| SS 256 | `phase_auto_0_S_256x256x256_42` (MT96x96/vw2/du16) | 412 | +320% |
| SS 1024 | `phase_auto_0_ss_1000x1000x1000_0` (MT128x128/vw4/du8) | 1135 | +14% |
| DD 192 / 768 | `auto_0_dd_1365x1365x1365_7` / `auto_0_dd_768x768x768_3` | 21.0 / 93.0 | +9% / +4% |
| HH 256 | `phase_auto_0_hh_256x256x256_4` (MT32x64/vw4/du16) | 206 | +24% |
| HH 512 | `phase_auto_2_hh_1024x1024x1024_2` (MT128x128/vw8/du16) | 1564 | +19% |
| HH 1024/2048/4096 | same kernel | 2368/2494/2665 | +3/+9/+16% |
| CC 192 | `phase_auto_0_cc_192x192x192_2` (MT32x32/vw2/du8) | 43.2 | +7% |
| ZZ 128 | `phase_auto_0_zz_128x128x128_16` | 16.8 | +154% |
| HH_HPA 512 | `phase_hh_hpa_Ailk_Bljk_mt128x64x16…` | 406 | +22% |
| HS_HPA 512 | `phase_hs_hpa_spoof_baseline_vega10` | 380 | +23% |

These are the reuse loss from §8.1's overlay-only-last-gen behavior: 425 measured
functional candidates sat in the run but never made any yaml.

### 8.5 Why "CU occupancy" reads ≤3 everywhere

The kernel metadata (`00_Final/cache.yaml`) carries `MaxOccupancy: 40` and the
model's `occupancy_workgroups_per_cu` reports `VGPR_PER_CU // acc` = 1024–2048 —
**both are register-slot counts, not resident workgroups**, so neither is what a
report of "≤3" is describing. The real per-CU residency, given 64 KB LDS/CU and a
per-workgroup tile footprint `(MT0+MT1)·bpe·DU`:

| kernel | LDS/workgroup (no dbuf) | resident wg/CU (LDS-bound) |
|---|---|---|
| SS `MT128x128x8/8x8/VW4` | (128+128)·4·8 = 8 KB (→≥16 KB dual-buffered) | **≤4 (≈2–3** with double buffer) |
| HH `MT128x128x16/8x8/VW8` | (128+128)·2·16 = 8 KB | **≈2–4** |
| ZZ `MT32x32x8/4x4` | (32+32)·8·8 = 4 KB | ~8 |

So the wide tiles the deck wins with land at **2–4 resident workgroups per CU**,
and the "≤3" is structural. It gets worse at small shapes: `SS 256` with a
128-tile has only 2×2=4 workgroups over 7 CUs — most CUs are idle regardless of
residency. Occupancy is therefore **not a knob to raise without shrinking the
tile**, and shrinking the tile is what the mid-shape losses are sensitive to
(the measured SS curve is non-monotonic across MT64/96/128). Treat "occupancy 3"
as a property of the wide-tile strategy, not a bug to fix in isolation.

### 8.6 Next candidates (CPU-gated PASS, TTY benchmark only)

Validated through `check_candidates.py` (all three gates) except where noted —
the two rejects are restatements of existing rules, listed so nobody re-proposes
them.

| id | target cells | config | gates | evidence |
|---|---|---|---|---|
| N1 | SS 512/768/1000/1365 | `64x64x8/8x8/VW4/DU8` | PASS | tile-downsizing occupancy probe; current best (MT128x128) loses 2–7% |
| N2 | SS 512/768/1000 | `64x64x16/8x8/VW4/DU16` | PASS | DU variant of N1 |
| N3 | SS 2048 | `128x128x8/8x8/VW4/GSU2` | PASS | GSU axis untried on SS; −2.0% left |
| N4 | HH 1024 | `128x128x32/8x8/VW8/DU32` | PASS | DU32 never tried; floor leaves −7.0% |
| N5 | CC 1024/2048 | `64x64x16/4x4/VW2/DU16` | PASS | current best is DU8; −3.9% left |
| N6 | CC 256 | `32x32x8/4x4/VW2/DU8` | PASS* | *fingerprint-identical to the CC 192 winner (`phase_auto_0_cc_192x192x192_2`) and subsumed by the seed overlay's winner row — removed from the seed as no-signal |
| N7 | DD 192 | `32x32x8/4x4/VW2/DU8` | PASS* | *fingerprint-identical to the DD 1365 winner (`phase_auto_0_dd_1365x1365x1365_7`) — same, removed |
| S1 | SS 768/1000/1365/2048 | **spoof-steal**: ship floor's `MT128x128x8/8x8/VW4/DU8` config as native (gfx900-ISA code object is allowed on this APU; this is literally what the floor arm runs) | PASS | closes the −4…−7% tail gap without a new config |
| S2 | HH 1024/2048 | spoof-steal `MT128x128x16/8x8/VW8/DU16` | PASS | closes −6…−7% |
| S3 | CC 256/1024 | spoof-steal `MT64x64x8/4x4/VW2/DU8` (+ `LdsPadA=2` variant) | PASS | closes −12/−4% |
| — | HH GSU2, SS `96x96x8/6x6/VW2` | — | **FAIL** | half assembly blocks GSU2 (Free0Multiple); 96-tile VW2 non-divisible — do not re-propose |

**Order of work (TTY only).** (1) run the current deck against the seed
overlay (§8 addendum, D2b — already implemented, nothing TTY-specific beyond
starting a run) so the 11 proven winners re-benchmark once against the live
GPU; (2) S1–S3 spoof-steal — highest expected value, tuned for gfx90c per the
D3 caveat, no rest of the tuning loop required; (3) N1/N4/N5 only if any tail
gap survives. Revisit D2 (the 21 pending iteration-9 phases) once the mutation
arm's per-run overlay behaviour is confirmed stable.

> **REOPENED as deficit-worthy (2026-10-09).** The previous "closed as *model*"
> note is rejected: it declared the CC/ZZ wall unfixable *before benchmarking
> the only knobs with a mechanism*, and misread the codegen. A fresh read of
> the vendored Tensile suite (commit e8a8999e) corrects the mechanism and
> exposes the real boundary:
>
> - **Instruction count is NOT the wall.** The non-MFMA complex MAC loop emits
>   exactly four `v_mac_f32` per complex MAC (the four emissions live in
>   `MAC_F32C.py:55/73/90/107` — the irreducible 4-real-MAC cost under BLAS-8
>   accounting; the older `KernelWriterAssembly.py:14975-14978` citation is the
>   beta epilogue — **superseded 2026-10-09 by `kernel_tuning_research.md` §5**,
>   which is now the canonical home). The
>   old "4–6 instr/MAC → ≈20 % of roof cap" figure is wrong: the ALU work is
>   already minimal, so the 69 %→20 % shortfall (SS reaches 1118.7 GFlops vs
>   CC 318.0 @512) is **memory/occupancy**, not instruction count.
> - **The gfx900 complex corpus is a 4-variable corner, not an exhaustive
>   sweep.** All 64 CC + 26 ZZ ships sit on MT{32,64,128} × TT{4x4,8x4} ×
>   VW{1,2} × WGM{1,8} with **GSU=1, LdsPadA/B=0, PGR=1, GRVW=VW, SUM=0,
>   SUS=256** on all of them. Axes other families ship and complex never got:
>   (a) `LdsPadA/B` — SS ships pads 1/2/4, HH ships 2/4/8 (manifest census);
>   pad-0/0 on every complex ship is exactly the 8/16-B-element bank-conflict
>   pattern the pad mechanism breaks, and Group C's small pads {1,2,4} are the
>   calibrated first probe; (b) `GlobalSplitU>1` — validator-legal for complex
>   via `GlobalSplitUAlgorithm=MultipleBuffer` (`_GlobalAccumulation` is set for
>   any GSU>1/MultipleBuffer at `SolutionStructs.py:2958-2976` and passes the
>   `supported` gate `:3543-3553`; the assembly writer explicitly handles
>   complex+GSU+MultipleBuffer at `KernelWriterAssembly.py:1726-1728,
>   2745-2747, 2912`); SS ships GSU up to 32 — complex wave-fill (§13.1 M2) was
>   never shipped; **(2026-10-09 superseded: the local gate refuses complex
>   GSU>1 on gfx90c — `scheduler:1379-1382`, Tensile `SolutionStructs:3553`
>   pass complex only via `_GlobalAccumulation` (set solely for
>   MultipleBuffer, `:2970-2971`), and this port never forwards
>   `GlobalSplitUAlgorithm`/workspace, so the run boundary refuses it and none
>   of the `:1726-2912` writer paths is reachable. Complex wave-fill via GSU is
>   NOT deckable in this port; see §13.5.) (c) `PGR∈{0,2}` (472 kernels ship PGR=0) — dropping
>   in-flight global-read VGPRs attacks the 2× complex register footprint
>   directly; (d) `NLCA/NLCB=3` (35/29 kernels) — fuses LDS load instructions.
> - **Deck state:** native CC/ZZ matches or beats the spoof floor on every
>   complex cell except **CC:256 (188.1 vs floor 214.0)** — the single
>   sanctioned complex steal, already tabled above (S3, `LdsPadA=2` variant).
>   The "orange" is relative to the %-of-roof bar, and the bar is not
>   construction: nothing in the 4-variable corner can cross 5×, but the
>   untried axes are the levers.
>
> **Resolution plan (ranked; TTY-only):** (1) **Group C pads** — `LdsPadA/B ∈
> {1,2,4}` on the CC/ZZ winners (shipped evidence: the pads AMD keeps are
> small, 1/2/4 B); (2) ~~**GSU=2+ wave-fill on CC** — MultipleBuffer + workspace,
> K-splits per §13.1 M2~~ — **withdrawn 2026-10-09**: complex GSU>1 is
> gate-refused on this port (scheduler:1379-1382; §13.5) — no K-split rows are
> decked for CC/ZZ; (3) **PGR=0** occupancy trade for the 2× complex
> register footprint; (4) **NLCA=3** LDS-load fusion — **scoped 2026-10-09**:
> legal only where NumLoads=3 side-wise (the ladder's 96x96x16/6x6/VW2 tile;
> 128-width VW4 tiles have NumLoads=1); (5) if pads+PGR stay
> under ~2×, escalate to **split-complex**: decompose each complex GEMM into 4
> real GEMMs + a combine pass (rocBLAS's pre-MFMA strategy) so complex runs at
> real-GEMM kernel efficiency — a client-side change outside the Tensile knob
> deck, budgeted only after 1–4 land. The M3 walls stay orange-on-paper
> **until these land in a TTY run**, not by construction.

### 8.7 Accuracy notes

`phase_auto_0_dd_1365x1365x1365_7`, `phase_auto_0_cc_*.` etc. bench a *grid* of
shapes per phase (each CSV covers 4–8 sizes), so "best at cell X" below is the
kernel's per-shape median, not its headline number. Row counts are per
kernel-shape; distinct kernels per cell are smaller. `n_native_runs` in the
report counts runs that touched the cell, so `CC:192 n=2` means two runs, not
two repeats — repeats are 8 inside every phase (`NumBenchmarks: 8`).

---

## 7 (dup) Decision log — continuation

- **2026-10-07** — Mutation-run post-mortem: 506 proposals (329/97/59/21); the
  overlay carries *only* the unmeasured iteration-9; the 425 measured functional
  candidates never reached any yaml (see §8.1, §8.4). The 97 legal_rejected are
  the pre-fix sampler inefficiency; the co-occurrence gate (this week) raised the
  legal rate 88%→100% (CPU-measured, 232/232, all families still propose).
- **2026-10-07** — `acceptance_report.json` SS cells were gfx90c-f16/HPA
  polluted: `phase_auto_2_hh_*` (f16) and `hh_hpa/hs_hpa` (half-input) kernels
  were being scored as f32 winners; SS "wins" at 1024/2048/4096 were physically
  impossible for f32. Corrected cells give **10 true losses**, including four SS
  mid cells the report called wins.
- **2026-10-07** — The C1/C2/C5 coverage-gap candidates were benchmarked by the
  mutation arm. Same config, best-median: native tail-gaps of −4…−12% remain
  (SS/HH/CC), i.e. the residual deficit is at best-seed level, not a missing
  row (see §8.3).
- **2026-10-07** — CU residency: the "≤3" observation is structural (wide-tile
  LDS ⇒ 2–4 resident wg/CU; plus <7 CUs of work at small shapes). The `wg/cu`
  values printed by `check_candidates.py` (1024–2048) are register-slot counts,
  not occupancy, and must not be quoted as such.
- **2026-10-07** — The 2026-10-07 run (3 mutations/10 iterations via both the
  CLI flags and the interactive entry) executed **nothing**: the mutation arm is
  measurement-guided (it can only mutate winners harvested from the *current*
  run's CSVs), the deck's phases were all `identical_fp_already_passed` by
  design, so 0 measurements → empty harvest → `converged([])` returns False → no
  mutations → stop at iteration 1. Not a regression; it is the skip/harvest
  contract behaving exactly. This is precisely what D2b's measure-once override
  exists for.
- **2026-10-07 — D2b seed overlay implemented and verified.** 16 rows (11
  winners with their shape grids + probes N1–N5) in
  `phases.seed.overlay.yaml`; `has_run_benchmarked(run_id, fp)` restores and
  extends the registry (the identical-fp method body was accidentally deleted
  while scoping it — restored under test), and `run_phases` gates the seed
  bypass to the first pass of a run (16/16 + curated each executed exactly once
  across 3 iterations in the dry harness). Full suite 585 passed (+4 seed
  tests), 1 skipped, 27 subtests.

---

## 9. Hardware grounding (2026-10-07, web-verified)

The peak rates in `gfx90c_common.py` are arithmetic identities, not guesses:

- `gfx90c` is the Cezanne (Ryzen 5000-series APU) Vega IGP — GCN 5.x / GFX9
  family, wave64, 448 shaders = **7 CUs × 64 lanes** at 1800 MHz boost →
  FP32 = 448·2·1.80e9 = **1.613 TF**, FP16 2:1 = **3.226 TF**, FP64 1:16 =
  **100.8 GF**. All three match the project's constants. (8-CU parts like the
  5700G are the same die at 2.0 GHz; the project device is the 7-CU bin.)
- Per ROCm's accelerator spec tables, GFX9 CU resources: **64 KiB LDS/CU** and a
  256 KiB VGPR file/CU. Both are the hard limits the occupancy gates model
  (§8.5's 2–4 resident wide-tile workgroups and the `error 4` rejections).
- GFX9 SGEMM tuning consequences that are *measured here*, not literature:
  1. 7 CUs make wave-quantisation real at every shape whose grid is not a
     multiple of 7 — the SS 512..2048 curve's non-monotonicity.
  2. DU8/DU16 (not 4) is required before the global load is covered, matching
     the floor's own choices (§3.1).
  3. Wide tiles (MT128×128) buy LDS-residency for a smaller payoff than a
     second resident workgroup because 64 KiB LDS only seats 2–4 of them.
  4. Anisotropic ZZ tiles (MT128×64/64×128, VW1) at 8 acc-registers per thread
     hit the register pressure that produces Tensile `error 4` — the 2026-09-26
     experiment died on exactly that (§10). Occupancy-first sizing (smaller
     MT, du up, VW ≥ 2) is the SOTA-correct direction for this class of part.

---

## 10. run_20260926_201835 root cause (ZZ anisotropic experiment, empty)

8 phases, all ZZ anisotropy (MT128×64/8×8·4 row, MT64×128, VW1, `wgm4_alu`).
Every one exits at `Generating kernel source resulted in error 4` with no CSV.
**Error 4 is the Tensile register-file occupancy failure** — the scheduler's
`occupancy_feasible` reproduces it CPU-side, which is why this run is correctly
absent from the native arm and why ZZ decks are gated so hard. Secondary noise
in `stderr.log` (Python 3.14 `loky` `semlock` cleanup warnings) is client-side
and did not contribute. No winners are hidden here; the run is best treated as
a live confirmation of the occupancy gate's §5.7 record.

---

## 11. All-run best-kernel-pattern analysis (2026-10-07, kernel_db sweep)

Best native kernel per cell across every measured run, from `kernel_db.json`
(rows aggregated gflops_median; `ss/hh/cc/dd/zz`-prefixed phases = native
arms, including the auto run). Two findings that are load-bearing for tuning:

| size → best native kernel (MT/tt/vw/du/gsu) | 256 | 512 | 768 | 1000–1024 | 2048 | 4096 |
|---|---|---|---|---|---|---|
| **SS** | MT96x96/6x6/vw2/du16 | MT128x128/8x8/vw4/du8 | same | same | same | same |
| **HH** | MT32x64/4x4/vw4/du16 | MT128x128/8x8/vw8/du16 | same | same | same | same |
| **CC** | MT64x64/4x4/vw2/du8 | same | same | same | same | same |
| **ZCZ 128/192/256/512** | MT32x32/2x2/vw1/du16 | MT32x32/2x2/vw1/du8(16) | same | same | MT64x32/4x2@1024 | — |
| **DD** | MT64x64/4x4/vw2/du8 | MT32x32/2x2/vw1/du8 | MT32x32/2x2/vw1/du8 | MT64x64/4x4/vw2 (1024+, 1024=64x32) | MT64x64/4x4/vw1 | — |

Observations:

1. **One tile per family covers the whole range.** SS is won by the SAME
   MT128x128/tt8x8/vw4/du8 kernel at every size 768→4096 (187–195 rows, best
   kernel unchanged); the only size that wants a different tile is the small end
   (256 → MT96x96/vw2/du16, the proven §8.4 winner). Widening/narrowing the tile
   per-cell (N1/N2 probes) is therefore **not** predicted to matter anywhere
   except the 512–768 knee and the small end.
2. **HH has a genuine size-dependent winner switch at the 256/512 boundary**
   (MT32x64/tt4x4/vw4/du16 → MT128x128/tt8x8/vw8/du16) — that is why HH 256 is a
   win and HH 1024/2048 stay losses: the floor's HH winner at the large cells is
   the same wide kernel the deck ships, and the residual is best-seed-level.
3. **CC is solved by exactly one pattern** (MT64x64/tt4x4/vw2/du8) at every size
   except 192 (MT32x32). The N5/N6 probes add DU/tile axes this sweep says are
   already settled; only CC 256's −12% tail gap (§8.2) is worth a probe.
4. **ZZ/DD winners are spread** across Mt32x32 tt2x2 vw1 du8/du16 and MT64x64 —
   multiple patterns within 2%, so no single "desert" tile exists for the double
   family; the ≲100 GF FP64 ceiling caps any further gain.
5. **The reference-arm rows ("S/H/C/Z/D"-prefixed, spoof/reference runs) sit
   LOW on the same cells** (e.g. SS 512 reference 577 vs native 771) — a
   discrepancy with the §8.2 tail-gap verdicts that must be reconciled per-cell
   per-dtype (cells_v2) before any §11 number is quoted in a report. The
   reference rows are the raw gfx900-spoof bests discussed in §8.6, not native
   re-measures.

Consequence for the tuning loop: the load-bearing knobs are **size-K
classified tiles** (small-end tile per family, wide tile above), and the only
unshipped real deficits are the best-seed tails (§8.3) — which the S1–S3
spoof-steal rows and the seed overlay (§8 addendum, D2b) target directly.

---

## 12. Programmatic regression matrix: deck vs ALL-time best (2026-10-07)

`gfx90c_results/analysis/regression_matrix.json` (regenerated by
`harness/regression_matrix.py` from `gfx90c_results/analysis/kernel_db.json`,
which `harness/kernel_db.py` rebuilds byte-identically from the run corpus)
compares, per cell `(family, shape)` of the shipped gfx900 grid
(`gfx90c_common.shipped_cell_set`, 38 cells — HH_HPA/HS_HPA are their own
cells, unlike the earlier dtype-collapsed view), the current **40-row deck's
best median** with the **all-time best measured median** across every native
run (`run_20260920_235815` … `run_20261006_122020`) and the gfx900 spoof floor
(`gfx900_ref_locked_52149f315d`), ranked by median GFlops (best-seed as
tiebreak only — §8.3 showed the `gflops_best` basis is tail-prone: e.g. the
D:192 all-time *best* 41.96 came from a kernel with median 17.67).

**Result:** **38 cells, 1 material median finding** — the deck ships the
median-best kernel for every cell except HH_HPA:4096, where the stranded
iteration-9 overlay candidate `phase_auto_1_hh_hpa_2048x2048x2048_4`
(measured in `run_20261006_122020`, not in the deck) sits **−4.0%** above the
deck's `MT64x128/4x8/VW4` at the median (1411 vs 1355). So the reuse-loss hole
§8.4 quantified (10 kernels absent from the deck) is closed for the 2026-10-06
mesh — with exactly one carry-over candidate left to ship (probe N7 below).
The best-seed-only gaps (D:192, H:256, Z:512 …) wash out at the median (§8.3).

**Deck-vs-floor residuals (median basis, the real remaining signal):**

| cell | deck best (MT/tt/vw/du) | floor best (MT/tt/vw/du) | gap | configs |
|---|---|---|---|---|
| C:256 | 188.1 (64x64/4x4/vw2/du8) | 214.0 (64x64/4x4/vw2/du8) | −12.1% | **identical** |
| H:1024 | 2367.9 (128x128/8x8/vw8/du16) | 2546.7 (128x128/8x8/vw8/du16) | −7.0% | **identical** |
| S:1365 | 998.7 (128x128/8x8/vw4/du8) | 1073.0 (128x128/8x8/vw4/du8) | −6.9% | **identical** |
| H:2048 | 2494.2 (128x128/8x8/vw8/du16) | 2658.0 (128x128/8x8/vw8/du16) | −6.2% | **identical** |
| S:768 | 1046.5 (128x128/8x8/vw4/du8) | 1094.9 (128x128/8x8/vw4/du8) | −4.4% | **identical** |
| S:1000 | 1029.7 (128x128/8x8/vw4/du8) | 1075.2 (128x128/8x8/vw4/du8) | −4.2% | **identical** |
| C:1024 | 289.7 (64x64/4x4/vw2/du8) | 301.4 (64x64/4x4/vw2/du8) | −3.9% | **identical** |
| S:512 | 771.9 (**128x128/8x8/vw2**/du8) | 801.6 (**128x128/8x8/vw4**/du8) | −3.7% | **vw differs** |
| S:2048 | 1098.2 (128x128/8x8/vw4/du8) | 1120.7 (128x128/8x8/vw4/du8) | −2.0% | **identical** |

Reading:

1. **8 of the 9 floor-loss cells benchmark the exact same kernel the deck
   ships.** The residual is *cross-run variance at the median*, not a missing
   knob or an occupancy effect — there is no configuration difference to tune.
   The only remaining experiment on these cells is a **re-measure**: carry the
   floor's kernel (which the deck already ships) in one run and see whether the
   deficit reproduces. Whatever it re-reports is the true per-cell floor gap.
   (S:2048 sits right on the −2% band edge; treat it identically.)
2. **S:512 is the single cell with a real config difference**: floor
   `MT128x128/8x8/VW4/DU8/GSU1` (801.6) vs the deck's `MT128x128/8x8/VW2/DU8`
   (771.9). This is the one knobs-level target on the whole board — a
   vw2→vw4 bump at SS 512. It joins §8.6's S-routes as a concrete candidate.
3. **The genuinely strong wins confirm the deck is sized right**
   (median-basis, per-family grid): **16 wins (>2%), 13 ties, 9 losses** vs the
   floor; S:256 +232%, S:1024 +3.2%, H:512 +12.6%, H:2048–… , Z:* +12…+243%,
   D:* ≈ parity (only 256/512/1365 at >+2%), C:192/512/2048 parity, and every
   HH_HPA/HS_HPA cell ≥ parity.
4. **One material median finding to ship, not to chase**: HH_HPA:4096's
   stranded overlay winner (`phase_auto_1_hh_hpa_2048x2048x2048_4`, −4.0% at
   the median over the deck's shipped kernel) is the only non-deck native
   kernel that beats the deck by >2% on any cell. It was accepted in the
   iteration-9 overlay and left un-shipped; add it as a D-row (probe N7) in
   the next deck edit.

**HH 256 reconciled (acceptance-report "LOSS" vs §12 "WIN" — a basis flip, not
a contradiction).** The acceptance-report scores best-seed per cell: floor
`phase_hh_gfx900_Ailk_Bljk_mt128-tt8-vw2-du8` measured best **303.6**, vs native
`phase_auto_0_hh_256x256x256_4` best 210.5 → "−31% LOSS". But that floor kernel
has a median of only **171.3** (its best seed is +77% over its own median), i.e.
*below* the native kernel's median. By median, the floor's best H:256 kernel is
`Ailk_Bjlk MT32x32/4x4/VW4/DU16` (201.5) and the deck's `MT32x64/4x4/DU16`
wins 206.5 (+2.5%, §1's table). One high single-seed on a wide=VW2 variant is
not a config signal — this is the §8.3 tail verdict on one cell. Same reasoning
applies to the CC 192 "43.2 GFlops" (§8.4) vs CC 512 "318" figures: both are
complex medians at different shapes (43 @ 192 → 318 @ 512 → 290 @ 1024), so no
unit inconsistency — complex kernels are simply a factor ~7 below the f32
peaks at equal size.

Recommended next TTY run (all are measured-once probes, not deck edits): carry
the 5 seed probes (N1–N5) **plus a sixth probe N6 = the SS:512 vw4 floor
kernel** (`Ailk_Bjlk, MT128x128, tt8x8, VW4, DU8, GSU1`) and keep one
re-measure pass of the 8 config-identical loss kernels — that isolates
variance from signal on every open cell in a single overnight. Deck-side, ship
the stranded HH_HPA:4096 winner **N7 = `phase_auto_1_hh_hpa_2048x2048x2048_4`**
as a D-row (it is already measured at −4.0% over the shipped kernel; only the
deck edit + one settle run are left).

**Occupancy gate (`scheduler.occupancy_feasible`), pre-run CPU check:** all
40 deck rows + 5 seed probes pass (0 failures); modelled register-file
workgroups/CU span 512–8192 — every row is launchable, so the overnight run
has no gate-blocked rows to trip `spawn_arms` at creation. (wg/CU here is the
register-file metric, not Gazebo occupancy; the low ≈3 figures elsewhere are
the LDS-bound residency view, see `results.md`/`knowledge_base.md`.)

---

## 8 (addendum) Decisions (2026-10-07) and their statuses

- **D1 — fold the §8.4 proven winners into the deck. IMPLEMENTED 2026-10-07.**
  The user explicitly approved it ("implement d1 from potential configs") after
  the earlier decline that spawned D2b. The 11 proven winners from §8.4
  (`phase_auto_{0,2}_*` URL rows + the CC 192/CC 256/HH_HPA 512/HS_HPA 512
  deck-born winners) are appended to `phases.yaml` as curated rows — `Ailk_Bjlk`
  pattern, `contraction_pattern` verbatim from source, `fp =
  fingerprint_config(config)` (self-consistency verified), `NumBenchmarks: 8`,
  `ScheduleName: isa`. The deck is now **40 rows** (29 archived + 11 D1).
  `check_candidates.py` validates all 40 (0 skipped, 0 illegal, exit 0).
  **Measure-once bootstrap:** D1 rows' fp was never recorded historically (run-55
  registry fps came from configs carrying the extra `WorkGroup`/`GlobalLoadVectorWidthA/B`/
  `AssertFree0ElementMultiple` keys), so the next run benchmarks each D1 row once
  and then settles — exactly the surviving-arm behaviour D2b was created for.
  `tests/test_consolidate.py::TestDeckIsVerbatim` was adapted: archive-sourced
  rows stay byte-identical to the archived deck; D1 rows are pinned by phase_id
  shape and the fp==fingerprint_config(config) contract. Suite: 603 passed,
  1 skipped, 27 subtests.
- **D2 — carry the 21 unmeasured iteration-9 phases into the next run's
  overlay.** The mutation arm spills candidates to a *per-run, write-only*
  overlay (`overlays/phases.<run_id>.overlay.yaml`); the last generation
  (21 configs, gated by the co-occurrence fix) was spilled after the budget
  expired, so those 21 were never benchmarked. **Confirmed by registry:**
  `phases.run_20261006_122020.overlay.yaml` holds 23 iteration-9 entries; the 2
  non-pending are `legal_rejected` at creation, the other 21 are stranded
  (`_load_run_overlay` reads only the *active* run's overlay, port_tensile.py:473).
  Cross-run continuation is by deck-consolidation only (D1 folded the winners);
  the strand is therefore superseded, not lost. Status: **open** (rows remain in
  the run dir + registry).
- **D2b (user-sanctioned replacement for D1+D2) — persistent seed overlay,
  IMPLEMENTED 2026-10-07, now carrying N1–N5 + the generated candidate pool
  (2026-10-08).** A static, run-independent
  overlay `gfx90c_results/overlays/phases.seed.overlay.yaml` is merged by
  `load_phases_manifest` on every run (origin `seed_overlay`, tagged
  `overlay_run_id: seed`, `phases.yaml` provably untouched). Post-D1 it carries
  **5 probe rows (N1–N5)** — the 11 winners now live in the deck (§D1 above),
  so keeping them in the seed as well would make them re-measure twice.
  `port_tensile.run_phases` treats seed rows as **measure-once-per-run**: the
  iteration-1 first pass re-benchmarks each row against the live GPU (this is
  the intended behaviour so the arm re-derives them), after which
  `registry.has_run_benchmarked(run_id, fp)` gates the identical-fp bypass off
  for the rest of that run — a static seed never re-fires on every iteration
  (verified: 16/16 pre-D1 seed + curated, each executed exactly once across 2
  iterations in the D1 dry run). Two planned probe rows were pruned during
  validation: N6/N7 v2 were *fingerprint-identical* to the CC 192 and DD 1365
  winners (same MT/tt/vw/du, different shapes only) and added no signal.
  Runtime: 603 passed, 1 skipped (+4 new tests in `tests/test_phase1_integration.py`).
- **D3 — S1–S3 spoof-steal rows (§8.6) as native deck entries.** Status:
  **proposed, not implemented.** Caveat recorded with the proposal: do **not**
  ship the gfx900 code object raw-textured as a "win." S1–S3 must be a gfx90c
  *tuned* re-compile of the winning gfx900-ISA pattern — same MT/tt/vw/du as
  the floor's best (MT128x128x8/8x8/VW4/DU8 for SS, MT128x128x16/8x8/VW8/DU16
  for HH, MT64x64x8/4x4/VW2/DU8 for CC) but re-targeted and documented, since
  gfx900 (Vega10, 64 CUs, 8 CU's worth of LDS per partition) and gfx90c
  (Cezanne, 7 CUs) have starkly different residency economics. The seed overlay
  gives a second, cheaper way to test the same pixel: its N1–N4 probes are the
  gfx90c-native expressions of the small-end tile hypothesis.

- **D4 — generated seed candidate pool (2026-10-08), IMPLEMENTED.**
  `harness/generate_candidates.py` emits a 287-row config->shapes candidate
  pool intended so a single overnight run finally has enough candidates to
  iterate (the 2026-10-08 short run exposed that the native arm had ~0 novel
  proposals to make). One row per config (fp is shape-independent; a row
  carries ALL of its family's in-grid target cells, matching deck semantics),
  three tiers:
  - **wide (252)** — redescends the family's ladder tiles x contraction
    patterns x DepthU (8/16, or the tile's pinned DU) x GSU ∈ {1,(2)} x WGM 4,
    spanning every in-grid target cell per family;
  - **narrow (24)** — 1-knob neighbours of each cell's deck winner
    (NARROW_NEIGHBOURS: MacroTile/ThreadTile/VectorWidth/WorkGroupMapping/
    GlobalSplitU), merged onto the wide row whose config (fp) already measures
    them, never duplicated;
  - **auto (1 standalone + 1 merged)** — evidence-derived explicit rows N6
    (SS:512 floor-vw4, merged into a wide row) and N7 (HH_HPA:4096
    128x128x16/8x8/VW4/DU16; standalone because HH_HPA wide patterns are
    `[:2]` and exclude Ailk_Bjlk);
  - **probe (10)** — off-grid cells (SS 32/64/128, DD 128) at forced DepthU 4
    in a *separate* pool (`graded: false`, origin probe_C*, never shipped;
    structurally disjoint from the in-grid pool by construction).
  **Parity-correct placement:** only the 277 in-grid rows land in the seed
  overlay (a §6.1 parity rule pins every overlay row to the shipped grid —
  `test_seed_only_extends_within_grid` — so `--with-probes` is the explicit
  opt-in that breaks it until the rule is amended). The 10 probe rows are
  always preserved in the mirror under a `probes` key.
  Verified end-to-end CPU-side: unique phase_ids + fps, zero collision with
  deck/seed fps, per-cell coverage, pool<->probe fp disjointness, and all
  277 seed rows pass the actual launch-boundary writer `_write_phase_config`
  (both CPU gates; 0 refusals). Appended to `phases.seed.overlay.yaml`
  (now 282 rows = 5 curated + 277 generated); standalone mirror preserved at
  `gfx90c_results/overlays/phases.candidates.20261008_024733.overlay.yaml`
  (287 rows under `phases`, 10 under `probes`) so after the overnight run the
  `phase_cand_*` ids can be stripped from the seed file to keep later runs
  light. `tests/test_library_parity.py`: 17/17 green with the pool in place.
  Ceil model was still %-of-f32/f64 roof for CC/ZZ at this date — since
  **REOPENED as deficit-worthy** (§8.6 note / §13.5, 2026-10-09; the "closed as
  model" verdict was rejected — see the reopened note);
  candidates include a pattern-overlap with deck favourites only via `[:2]`
  wide patterns — deck's other patterns remain deck-only. Runtime: full suite
  not re-run; generator unit coverage lives in `tests/test_generate_candidates.py`.

---

## 13. run_20261008_030033 triage: why "nothing moved towards the ceiling" (2026-10-08)

Ground truth for this section, all verified locally:

* acceptance report: `gfx90c_runs/run_20261008_030033/acceptance_report.json`
  (`PROVISIONAL FLOOR`, reference re-measurement declined; 22 WIN / 15 TIE / 1 LOSS).
* native per-kernel medians: `harness/kernel_db.py` over `kernel_db.json` (note:
  **it does not contain `run_20261008_005217` or `run_20261008_030033`**; those
  two were scanned ad hoc in §12 triage. Rebuild it with `--rebuild` before the
  next verdict so every run participates).
* spoof per-cell bests + knobs: the locked floor `gfx900_ref_locked_52149f315d`
  rows in `kernel_db.json`, typecode-filtered (`SB/DB/HB/CB/ZB` only).
* newest-run per-candidate medians: extracted per-phase from
  `run_20261008_030033/phase_*/2_BenchmarkData/*.csv` with `phase_survey`.
* hardware/occupancy model: `gfx90c_theoretical_limits.md` §6 and the web-sourced
  occupancy rules (session 2026-10-08): 7 CUs = 28 SIMDs = 280 wave slots; per
  SIMD dependent on per-thread VGPRs (≤24→10, 32→8, 48→5, 64→4, 256→1 waves);
  LDS 64 KB/CU budgeted as WG=256thr→≤64 KB/WG, WG=128thr→≤32 KB/WG.

### 13.1 Four mechanisms, one headline

**M1 — ceiling saturation (ties that are walls).** On the large squares the
machine is ALU/pipe-bound and the deck already reaches (or crosses) the
occupancy-corrected realistic ceilings, exactly like the gfx900 ships. SS 768+
native ≈ **1046–1135** vs realistic ceiling **1118.7** (93–102 %); HH 1024+
native ≈ **2368–2665** vs **2461** (96–108 %); DD 768+ native ≈ **89–97** vs
**98.6** (90–98 %); HPA/HS 512+ native ≈ **773–1441** vs the derived **1118**
bar (HPA sits *above* 100 % because the f16 input footprint halves
LDS/VGPR traffic — the derived ceiling intentionally under-states it). Native
and spoof land within ±5 % of each other on every one of these cells:
SS:768 **-0.5 %**, SS:1365 **-2.9 %**, DD:768 **+1.5 %**, DD:2048 **+0.4 %**,
H:1024 **-3.9 %**, H:2048 **-3.1 %**, H:4096 **+0.1 %**, HPA:1024 **+0.1 %**.
**These ties are not tuning failures and no config mutation moves them.** The
"bunch of ties" the user saw is mostly this: both arms pinned to the same wall.

**M2 — wave quantization ("lack of work") on the small cells.** For a
cube of side N with tile MT, total waves = (N/MT0·N/MT1)·threads-per-WG/64.
Practical counts on 28 SIMDs (full table below):

| cell | winning tile (tt) | total waves | waves/SIMD | ~residency |
|---|---|---|---|---|
| SS:256 | 96x96/6x6 | 36 | 1.29 | 13 % |
| SS:512 | 128x128/8x8 | 64 | 2.29 | 23 % |
| HH:256 | 32x64/4x4 | 64 | 2.29 | 23 % |
| HH:512 | 128x128/8x8 | 64 | 2.29 | 23 % |
| CC:256 | 64x64/4x4 | 64 | 2.29 | 23 % |
| CC:192 | 32x32/4x4 | 36 | 1.29 | 13 % |
| DD:192 | 32x32/4x4 | 36 | 1.29 | 13 % |
| ZZ:128 | 32x32/2x2 | 64 | 2.29 | 23 % |

A 192/256 cube with sensible tiles simply cannot *produce* ≥~40 waves — the
machine idles below 25 % residency. SS:256 makes 412/1613 while SS:1024 makes
1135/1613 with 91 % residency — **the gap between them IS the residency gap.**
These small cells are the real "headroom", and the lever here is not the tile
shape but **filling the 7 CUs**: smaller tiles that still keep ≥4 waves per
thread in flight, or GlobalSplitU to turn waves over K. §7's `256 → GSU8`
note is exactly this.

**M3 — the Tensile complex throughput wall (CC and ZZ).** At 512..2048 the CC
kernels cap at **≈290–318** GFlops and ZZ at **≈21–24**, and the gfx900 ships
hit the same plateau (spoof CC:512 317.8, ZZ:1024 22.6) — but the earlier
"codegen cap ≈ 20 % of roof" reading behind this wall is **rejected**
(2026-10-09, §8.6 note / §13.5): the complex MAC loop is exactly four
`v_mac_f32` per MAC (`KernelWriterAssembly.py:14975-14978`), so the shortfall
is memory/occupancy, not instruction count (within the ships' 4-variable
corner the CC/ZZ rows sat in a ±3 % band — the corner, not physics). Working
mechanisms, in order of confidence: (a) 8-byte (C) / 16-byte (Z) LDS elements
at LdsPad=0 amplify bank conflicts versus 4-byte elements — the pad axis
(Group C, §13.6: now forwarded + gated, small pads {1,2,4}) was never
benchmarked; (b) complex A/B/C double the register footprint, and the ships'
PGR=1 + GSU=1 leave both the fragment count and the wave-fill (§8.7 M2)
untouched — SS ships GSU up to 32, and complex GSU>1 is validator-legal via
MultipleBuffer (`SolutionStructs.py:2958-2976/3543-3553`); (c) Z's VW1 (16-B
cap) caps C-reg reuse. Pad + GSU + PGR probes are the resolution path (see
§8.6 note), not a config-deck dead end.

**M4 — the run itself was measured at a suppressed clock.** The newest run's
samples carry `native_clock_coverage: 0.53` and `native_clock_sclk_hz:
1175000000` against `sclk_ref_hz: 1800000000` → **≈1.53× slower than the
reference clock**. Its absolute GFlops look "flat" partly because they are
~50 % lower than any full-clock run would produce (CC:256 pool rows ≈55 while
the old full-clock deck did 188; SS pool rows ≈130 while 412 was known).
Crucially: **its wins are within-run-relative and valid** (CC WGM8 315.4 >
WGM4 300.9 at 512 within the same clock), but its absolute values and any
verdict delta against the 1.8-GHz locked floor are **not comparable**. Apollo
DVFS on a 6-hour TTY-less iGPU soak drifts 1.2–1.8 GHz; either the bench must
pin sclk (e.g. `sclk=1400MHz`) or verdicts must be clock-normalized before
grading. Also note the acceptance `native_value` is best-of-bests across runs
→ it mixes clock regimes cell by cell; the report already stores the clock
fields, we just don't consume them.

### 13.2 Contamination that already affects the published verdicts

Three classes, all reproducible in-place — **this report is not reportable
until report.py/analytics are audited**:

1. **S cells "won" by H-family phases.** `S 512 native_value=1419.93`
   (`phase_auto_1_hh_4096x4096x4096_2`), `S 1024=2142.55`
   (`phase_auto_1_hh_1024x1024x1024_3`), `S 2048=2092.51`
   (`phase_auto_2_hh_512x512x512_1`), `S 4096=2068.03`
   (`phase_auto_1_hh_1024x1024x1024_3`) — every one an `hh`-prefixed phase.
   Typecode-filtered, the honest SS cells are **1135 / 1098 / 1091**
   (native) vs **1100 / 1121 / 1110** (spoof) = ties at the ceiling.
2. **Same-phase cross-shape attribution.** `H 512 native_value=1564.07` comes
   from `phase_auto_2_hh_1024x1024x1024_2` (a 1024-phase) and `H 256
   763.38` from `phase_auto_0_hh_256x256x256_4`, whose 256-shape samples in
   the kernel_db runs sit at ~180–206. The 763 value comes from the *two runs
   absent from kernel_db*; it may be a true full-clock measurement, but right
   now it is **not reproducible from the corpus** and should not be quoted.
   (Fix = fold 005217/030033 into `kernel_db.json`, then every number in the
   verdict table is re-derivable.)
3. **Newest run undercounted.** See M4 — absolute numbers need the ≈1.53×
   clock factor before they can be compared with the floor at all.

Fair re-tally of the 38 cells **before** any tuning: the four S-cell "WIN"s
reclassify as TIE; that gives roughly **18 WIN / 19 TIE / 1 LOSS** (HPA/HS,
DD, H:256/512 and ZZ wins stand; CC:256 remains the single honest LOSS). 36 of
38 cells either sit at a wall (M1/M3) or are measurement artefacts (M4/M2).

### 13.3 Kernel-type patterns (all runs, all families) — what actually wins

| lever | winner | evidence |
|---|---|---|
| direction | `Ailk_Bjlk` (**NT**) dominates | the only non-NT winners are the DD:192 `Alik_Bljk` (TT) and the DD/Z 1024 pocket `64x32` TN tiles; spoof is NT-everywhere too |
| MacroTile | ∝ 1/element-size: S/H 128 (96 at 256), C/D 64 (32 at 192/256), Z 32 (64x32 at 1024) | every family's whole range is served by ONE tile at the large end + one at the small end (§11) |
| VectorWidth | pinned to the 16-B load cap, not free | S vw4=16B, H vw8=16B, C vw2=16B, D vw1-2=16B, Z vw1=16B, HPA vw4 |
| DepthU | 8 for S/D/C/Z, 16 for H/HPA (+ SS:256 96-tile = du16) | pattern is family-locked, not a knob to sweep |
| WorkGroupMapping | 4 everywhere; **8 is a real CC lever** | CC 512 WGM8 315.4 > WGM4 300.9, CC 1024/2048 WGM8 wins the cells (within-run, M4-safe) |
| GlobalSplitU | 1 in *all* winners | GSU never validated for fills; the only untested large-winning axis (see 13.4) |
| register hygiene | widest scale: real families saturate; complex families cap at the throughput wall (reopened 2026-10-09) | M1/M3 |

### 13.4 Candidate plan (CPU-gated legality PoCs here; TTY-only benchmark)

**Group A — wave-fill the small cells (M2).** These have residency headroom
and GSU is the cheapest way to add waves without rarefying the tile. All
patterns NT unless noted; run at 3+ seeds, judge within-run.

* **SS:256** — currently 412 (96x96/6x6/du16/GSU1, 36 waves). Add the same
  tile at **GSU {2, 4}**, plus **64x64x8/4x4/vw4/GSU {2,4}** and
  **64x64x16/4x4/vw4/GSU2** (each 64-waves base). Target ≥550 (35 % res on
  the 1118 realistic).
* **SS:512** — 772 at 128x128 (64 waves). Add GSU{2,4} on 128x128 and on
  64x64x16/4x4/vw4. Target ≥900.
* **HH:256** — 763 (32x64/4x4/vw4/du16 = 64 waves). Add **GSU2** (half
  GSU>1 requires AF0EM≥2 — legality gate must enforce) on the same tile and
  on 64x64x16/8x8/vw8. Target ≥1200 (i.e. ~1.6×).
  > *Superseded 2026-10-09: HH GSU2 is NOT re-proposed — the §8.6 candidate
  > table's FAIL row (Free0Multiple blocks ~half the HH phases, "do not
  > re-propose") stands; HH wave-fill proceeds via 64x64 alternates only, see
  > §14.5 item 2.*
* **HH:512** — 1564 (128x128, 64 waves). GSU{2,4} variants.
* **DD:192/256/512** — already WIN; a GSU{2,4} probe on the 32x32/2x2 winner
  is cheap and may push 192 past 60.

**Group B — fix the single honest LOSS: CC:256 (−11.4 %).**
The spoof's winner IS `Cijk_Ailk_Bjlk_CB_MT64x64x8` / tt4x4 / vw2 / du8 /
GSU1 (measured 214). Native best for the cell is the same geometry in the
`Alik_Bljk` (NK) direction at 188. The sanctioned spoof-steal here is exact:
benchmark **`Ailk_Bjlk` + WGM8 and WGM4`** at 256 with ≥3 seeds (WGM8 on this
kernel already wins 512+), plus the wave-fill alternates **64x32x8/4x2** and
**32x64x8/2x4**. The delta to beat is ~14 %, likely clock + direction + WGM
combined; no other cell needs a steal.

**Group C — the CC/ZZ codegen lever (M3).**
> Superseded 2026-10-09: Group C landed (forwarding + the `ldspad_feasible`
> gate, §13.6) — pad probes use the shipped-domain values {1,2,4} (scheduler.py
> rows, not the {0,16,32} sketched here), and the reopened §8.6 note extends the
> mechanism set beyond pads to GSU>1 (MultipleBuffer), PGR=0 and NLCA=3. Text
> below is the dated (2026-10-08) plan, kept for the record.
`_write_phase_config` silently drops `LdsPadA/LdsPadB` (+ `StaggerUStride`,
and there are no `swizzle/layout` options forwarded either). Before any
complex micro-tuning, **forward those knobs through the writer + a legality
gate in `scheduler.validate_config`/`occupancy_feasible`** (CPU-side, one
session), then propose CC/ZZ variants on the current winners:
MT64x64x8 (CC), MT64x32x8 / 32x32x16 (ZZ) with LdsPadA/B ∈ {0,16,32} and,
if Tensile accepts local swizzle, the conflict-free M/N layouts. This is a
hypothesis: 8/16-B LDS elements bank-conflict the current kernels into the
~20 % cap; padding/swizzle is the documented Tensile remedy. Cost is small
(2 families × ~6 phases).

**Group D — measurement hygiene (do this before trusting any verdict again).**
1. Fold `run_20261008_005217` + `run_20261008_030033` into `kernel_db.json`
   (`--rebuild`) so every number is corpus-reproducible. 2. Re-derive every
   cell with the **typecode filter** (SB/DB/HB/CB/ZB only) — §13.2 shows four
   S cells and at least one H cell flip. 3. Clock-normalize or pin sclk
   (~1.4 GHz) so run deltas are meaningful; at minimum surface
   `native_clock_coverage < 0.8` as a warning in the acceptance report.
4. Regenerate the verdict table once 1–3 land: **expect ~18 WIN / 19 TIE /
   1 LOSS**, with the "19 ties" being ≥10 genuine wall ties (M1) + 2–3 M2
   cells that Group A can convert + the CC/ZZ wall (M3) awaiting Group C.

### 13.5 Ceiling-model caveat (REOPENED 2026-10-09)

The realistic ceilings for CC (**1118.7**) and ZZ (**98.6**) are derived from
the f32/f64 roof and do NOT subtract any Tensile-complex penalty. The previous
"closed as model / permanent orange by construction" verdict is **rejected**
(§8.6 note, 2026-10-09): the "4–6 instr/MAC → ≈20 % cap" claim does not survive
a read of the assembly writer — the non-MFMA complex MAC loop is exactly four
`v_mac_f32` (citation home: `kernel_tuning_research.md` §5 / `MAC_F32C.py:
55/73/90/107`), so the shortfall is
memory/occupancy, and the untried legal axes (`LdsPadA/B` small pads {1,2,4},
PGR=0, NLCA=3) are all shipped-elsewhere knobs the
64 CC + 26 ZZ gfx900 ships never sampled (GSU=1, pads 0/0, PGR=1, GRVW=VW on
every one). The walls stay open until those probes land in a TTY run. The one
already-quantified complex deck loss is **CC:256 (188.1 vs floor 214.0)**,
addressed by the sanctioned Group B steal (§8.6 table S3, `LdsPadA=2` variant).
No ceilings-table amendment is owed — the bar itself is the acceptance target.

> **Superseded 2026-10-09 (night) — complex GSU>1 and NLCA scope.**
> (1) **GSU>1 for complex is NOT deckable in this port** (was "validator-legal
> via MultipleBuffer" above): Tensile passes complex only through
> `_GlobalAccumulation` (`SolutionStructs:3543-3555`, set solely for the
> MultipleBuffer algorithm) and the local gate refuses it on gfx90c
> (`scheduler:1379-1382`); the port does not forward
> `GlobalSplitUAlgorithm`/workspace, so the run boundary would refuse the
> kernel. The §8.6 rung-2 row and §14.5 item-3c "GSU2+workspace" lever are
> withdrawn; the complex residency ladder is now **pads {1,2,4} → PGR=0 →
> NLCA (3-load tiles only) → split-complex**. (2) **NLCA=3 needs NumLoads=3
> side-wise** — the ladder's 96x96x16/6x6/VW2 tile is the only 3-load shape
> (128x128x8/VW4 has NumLoads=1, so NLCA>1 is refused there).

### 13.6 Post-fix results (2026-10-09) — the contamination fixes + measurement hygiene land

All four Group D items are done and verified on the REBUILT kernel_db (both
missing runs folded → 19 608 rows, 8 runs with data):

1. **Typecode-attributed cells, zero contamination.** `FAMILY_TO_DTYPE["auto"]`
   was the root cause (§13.2): `phase_auto_*` ids matched the greedy 4-char
   pool prefix → family `'auto'` → dtype `'S'` → HH/CC/DD kernels tallied into
   the SS cells. Removed; `gfx90c_common.kernel_typecode()/
   family_from_kernel_name()` are now the single resolvers (layout-suffix-aware:
   `HHS_BH`, `ZB_GB`), `resolve_cell_family()` is typecode-first with
   `[contamination]` warnings, `aggregate_by_cell_typecode()` partitions rows by
   kernel. Rebuilt-DB audit: **0 family↔typecode disagreements, 0 HH-ish kernels
   in any SS cell, 0 `phase_auto_1_hh` rows in SS:1024**. Honest SS cells:
   256 412.1 / 512 801.5 / 768 1094.9 / 1000 1107.4 / **1024 1135.1** / 1365
   1073.0 / 2048 1120.7 / 4096 1123.0. (256/1024 match the §13.2 audit exactly;
   the rest rose because the newest run's rows now participate.)
2. **Floor winner gate-legality proven.** `check_candidates.py --floor` sweeps
   the 6 855-kernel manifest rebuilt into configs: **all 30 per-cell floor
   winners pass all 4 gates**; whole-deck residue 1 464 (21 %) = GLVW/VW
   divisibility artifacts (738) + assembly-class (357) on non-winning shipped
   entries + 72 genuine occupancy-LDS (64-KB-LDS gfx900 kernels the APU
   rejects — never won a cell).
3. **VGPR model measurement-ratified.** `harness/measure_vgprs.py` reads real
   per-thread totals from Tensile-emitted objects (1144 scanned, 605 mapped);
   invariant (gate-legal ⇔ measured < 256) holds for every (dtype, TT) —
   table in `scheduler.MEASURED_VGPR_BY_DTYPE`.
4. **Auto-pool is NOT marginal (audit resolves the todo-6 hypothesis).** The
   auto phases win **13/34** cells natively (38 %), incl. HH:256 763.4, SS:1024
   1135.1, SS:256 412.1, DD:768 93.0, CC:192 113.8; the legacy
   `phase_auto_0_{S,Z}_*` pool (117 dirs) wins 10 cells by typecode attribution.
   Keep them; rename the single-letter tokens at hygiene time.

Also landed: **Group C forwarding** — `_write_phase_config` now forwards
LdsPadA/B, AssertFree0ElementMultiple, StaggerUStride, StoreCInUnroll behind
the CPU-only `scheduler.ldspad_feasible` gate (padded-LDS footprint ≤ 16 384,
StaggerUStride < DepthU·bpe, AF0EM ≥ 1), and the generator's `_FORWARDED` set
keeps them on candidates; 4 Group C tests. Tooling: `harness/cell_knob_diff.py`
(per-cell native-vs-floor winner knob deltas: 30 cells shared, 22 native /
8 floor — CC:256 188.1 vs 214.0 is the single outside-band LOSS and the only
sanctioned steal — *superseded 2026-10-09 by the §14.1 band tally on the same
rebuild: 17 native / 8 tie / 5 loss; the "single" phrasing predates the
SS/HH cross-run clock audit, which re-classed SS:512's VW2 pick and the three
same-kernel SS/HH rows — see §14.2. CC:256 remains the sanctioned steal.*), `--prune-candidates` on the generator, occupancy-margin
output in `check_candidates.py` (`wg/cu=N acc=…vgpr …% of 64K file`).

### 13.7 The tuning cookbook

All of the above, formalized with the knob surface, the M1–M4 mechanisms, the
measured patterns, and the overnight-run rules, lives in
**`gfx90c_tuning_guide.md`** (caveman, full). The acceptance bar remains
`gfx90c_theoretical_limits.md` §5.

## 14. Beat-the-spoof campaign — tie/loss anatomy, occupancy audit, all-around plan (2026-10-09)

> Status: analysis + CPU-gated legality only (GNOME rule — no GPU stress).
> Every benchmark below is TTY-only. Fresh facts computed 2026-10-09 from the
> typecode-corrected `kernel_db.json` rebuild via
> `python3 harness/cell_knob_diff.py` (verdicts) and
> `python3 harness/occupancy_audit.py` (residency); both are the reproducible
> homes of the counts cited here — do not re-transcribe them elsewhere.

### 14.1 Verdict anatomy — 17 native / 8 tie / 5 loss (|Δ| ≤ 2 % tie band)

Of the 30 shared cells, the |Δ| ≤ 2 % band tally is **17 native wins, 8 ties,
5 losses**. Per family (full per-row numbers run from `cell_knob_diff.py`):

- **SS (8 cells): 3 W / 3 T / 2 L.** Big native wins at 256 (−69.9 %), 1000 (−2.9), 1024 (−3.1);
  knife-edge ties at 768 (+0.5 floor), 2048 (+1.4 floor), 4096 (−1.2 native); losses at 512 (+3.8)
  and 1365 (+3.2) — **both losses ride the SAME MT128x128x8 kernel as the floor**, so the deficit
  is knob- or clock-level, never tile-level.
- **DD (7 cells): 4 W / 3 T / 0 L.** The cleanest family — floor's wide 64x64 tiles lose to
  native 32x32 on 7 CUs everywhere (best −59.4 % at 192; 1365 −2.6). 768/1024/2048 sit inside the
  band (native-side, −1.3/−1.5/−0.2).
- **HH (5 cells): 2 W / 1 T / 2 L.** Massive native wins at 256 (−73.6) and 512 (−11.2); 4096 is a
  +0.1 tie; **1024 (+4.0) and 2048 (+6.6) lose with the byte-identical kernel both sides** — the
  largest same-kernel deltas in the deck.
- **CC (5 cells): 3 W / 1 T / 1 L.** 192 −62.0, 1024 −3.0, 2048 −4.3 native; 512 −0.0 tie;
  **256 +13.8 — the deck's only loss above 10 %.**
- **ZZ (5 cells): 5 W / 0 T / 0 L.** −70.8 ⋯ −5.7. Also clean.

The 8 cells outside the 30 are extension-only (one arm absent) and out of the A/B
verdict by construction.

### 14.2 Why each loss happens — four mechanism classes

1. **Clock/queue artifact (SS:1365, HH:1024).** Both native medians come from
   `run_20261008_030033`, the run whose telemetry measured sclk at **1.175 GHz**
   (53 % native clock coverage; ref 1.8 GHz — M4). The floor medians come from the
   September `gfx900_ref_locked_*` chain. No verdict anywhere is clock-normalized
   (`clock_adjusted: False` in every acceptance row; `spoof_clock_coverage: 0.0`
   every cell). A 3.2–4.0 % delta sits inside that run's ~50 % suppression envelope →
   **no config signal; re-measure, do not re-tune.**
2. **Same-kernel cross-run noise (HH:2048).** Both arms are the identical solution
   (MT128x128x16/8x8/VW8); the floor measured 6.6 % higher on its day. Without clock
   pinning, ±2–4 % drift is the measured noise floor (the §8.4 HPA rows show the same
   spread). **No config signal.**
3. **Suboptimal native pick at the M2/M1 boundary (SS:512).** Native won with **VW2** on the
   same MT128x128x8 tile where the floor ships **VW4** (= the 16 B/cap global-load vector
   width). VW2 halves GLVW (8 B loads → more outstanding loads) and raises wg residency in
   the VGPR-bound regime — it won on that run's clock, but under-delivers vs the floor's VW4
   at M1. Fix = probe **VW4@512 + GSU2** (the banned `96x96x8/6x6/VW2` variant
   is not re-proposed — §8.6 candidate-table FAIL row).
4. **Real direction + residency deficit (CC:256 — the sanctioned steal).** Native winner
   `Alik_Bjlk` vs floor `Ailk_Bjlk`, same MT64x64x8/4x4/VW2 geometry, +13.8 % floor. Mechanism
   stack: M3 complex wall (4 real MACs per mac; §7/§13.5) + M2 starve (3 resident wg/CU →
   12 waves/CU = 30 %, §14.3) + direction. Action: §8.6 S3 steal-adapt + pads/GSU/PGR (Group C below).

The tie cells (8) are all the same-kernel-±2 % regime: the arms differ only by
cross-run clock/noise, and the honest response is measurement hygiene (below), not knobs.

### 14.3 CU occupancy — the "always ≤3" investigation (latest model, 2026-10-09)

**Repro:** `python3 harness/occupancy_audit.py` (new; uses
`scheduler.MEASURED_VGPR_BY_DTYPE` as register truth, `FAMILY_BYTES_PER_ELEMENT`
for LDS — note ZZ = 16 B/element).

**The ≤3 is real, and it is a physical property of the winning configs, not a model bug.**
On the current native winners: **25/34 cells sit at ≤3 resident workgroups/CU**
(min 2, median 3, max 10); waves/CU run 8–24 of the 40-slot budget (median 12 = 30 %).
Binding resource tally: **VGPR file 21 cells, LDS 13 cells** — i.e. wide thread tiles are
VGPR-bound (SS/HH wide: 256 threads × 119–199 measured VGPRs → 2–3 wg/CU), the rest LDS-bound
(double-buffered A+B footprint 8–32 KB → 2–4 wg/CU).

Two sharp results the audit adds over the earlier §8.5 estimate:

- **The spoof floor is NOT more resident.** Audit `--side floor`: 26/30 cells ≤3, median 3,
  same binders. Both arms share the tile geometries, so occupancy is **not where the floor
  wins** — CC:256 sits at 3 wg/CU on both arms, and the floor still takes it via direction +
  code-object tuning (class 4 above).
- **The wall is VGPRs, not LDS.** Single-buffer probe (`--lds-factor 1`): the ≤3 count barely
  moves (24/34) and VGPR becomes the binder for 33/34 cells. Frees LDS all you want — the wide
  tiles still starve on the register file. **Residency levers must free VGPRs**, in order:

  1. **GSU (wave-fill)** — splits K into G workgroups on the same tile: more workgroups, same
     per-thread VGPRs → straight wave-fill of idle SIMD lanes. The M2 tool (Group A).
  2. **PGR=0 / GLVW=1** — the prefetch A/B registers wide tiles burn are exactly what the
     VGPR binder counts; dropping prefetch raises VGPR-bound residency. Untried axis.
  3. **Smaller TT** (8x8 → 4x8/4x4) — halves-to-quarters the per-thread accumulator cost, at
     reuse/latency cost; only sensible where M2 starve dominates (SS:256/512, CC:256).
  4. LDS-side knobs (pads, single-buffer LDS, DirectToVgpr) are **secondary** — they matter
     only for the 13 LDS-bound cells (ZZ:128/256/512/1024, SS:32/192/256).

And the reconciliation with M1: the SS/HH wide cells hit 93–108 % of the realistic ceiling
**despite** 8–12 waves/CU because their loops are ALU-dense with short reuse distance — 8–12
resident waves already hide load/LDS latency. Raising occupancy there would mean smaller tiles
→ less register reuse → more traffic → net loss. Occupancy is the lever only where waves are
few (M2 small squares) — exactly the §13.1 M1/M2 split, now with numbers behind it.

> Note: `check_candidates.py`'s `wg/cu=N` line is `65536 // accVGPR`, a register-slot count
> (1024–2048 for small TT), **not** a residency — the §8.5 warning stands; read the audit tool
> for physical residency.

### 14.4 Kernel-type patterns across all runs (what actually wins)

Extends §13.3 (the patterns home) with the fresh winner set — pattern is stable and now
family-complete:

- **NT (Ailk_Bjlk) wins every family's large cells**; CC small cells run Alik (A-transposed)
  32x32x8/64x64x8 — the deck's only direction split, and it contains the one real loss (CC:256).
- **One tile per family per size regime** (tile width ∝ 1/bpe): S 128x128x8 (512→4096),
  H 128x128x16 (512+), D 32x32x8→64x64x8, C 64x64x8 (256+), Z 32x32.
- **VW at the 16 B/cap** (S:4, D:2, H:8, C:2, Z:1) — the sole anomaly is SS:512's VW2 pick
  (a candidate, not a pattern; §14.2 class 3).
- **WGM16 at wide tiles; WGM8 = the real CC lever**; GSU1 everywhere native (untried by runs,
  legal via `GlobalSplitUAlgorithm=MultipleBuffer`).
- **DU8 per K-slice; DU16 for H and the small D/Z blocks** — bigger K-slice hides reloads
  where the block is small.

### 14.5 The all-around candidate plan to beat spoof (wider + narrower, ranked)

**Prerequisite (M4): clock-pinned head-to-head re-measurement of the 30 shared cells.
`clock_adjusted: False` everywhere and native coverage at 0.53–0.54 with a 1.175 GHz median —
the five "losses" and most ties live inside the cross-run envelope. First TTY move: a same-run,
pinned-clock A/B before trusting any delta.**

> **IMPLEMENTED (decked 2026-10-09 night).** Items 1–5 below are now *emitted
> candidates* (generator `PLAN_BATCH`, tier `auto`, plus structural generator
> changes) in the regenerated seed overlay — 5 curated + 290 in-grid rows.
> Status per item; two decided levers were gate-refused and are superseded
> (see §8.6/§13.5 supersession markers above): complex GSU>1 (item 3c / rung 2)
> and NLCA=3 on 128-width tiles (item 4). NN = still TTY-only.

1. **SS:512 VW4 correction + GSU2** (Group A N3-style; `96x96x8/6x6/VW2` banned): the only
   knob-level native deficit on the M1 plateau; target is clawing the +3.8 % back.
   **DECKED**: the wide SS tier now sweeps GSU {1,2,4}, so the `128x128x8/8x8/VW4` GSU2/GSU4
   rows span SS:512 (N6 already covered the GSU1 floor kernel).
2. **Group A wave-fill on M2 cells** — SS:256/512 GSU{2,4} + 64x64 alternates;
   DD:192/256 GSU2; **HH:256/512 via 64x64 alternates only — HH GSU2 stays
   banned** (§8.6 candidate-table FAIL row: Free0Multiple blocks ~half the HH
   phases; "do not re-propose" — §13.4 Group A's HH line is superseded on this
   point, see the marker there). All these cells sit ≥25 % below the §5
   realistic bar at 20–60 % wave slots (§14.3) — the widest un-mined seam.
   **DECKED**: SS GSU{1,2,4} ladder; HH GSU>1 structurally banned (wide +
   narrow tiers, test-locked); HH:256 and DD:256 joined `TARGET_CELLS` so the
   HH 64x64/64x32 alternates and the DD GSU{2,4} narrow rows span them.
3. **CC:256 steal-adapt (worst loss, sanctioned).** Take the gfx900-source
   `Ailk_Bjlk` MT64x64x8/4x4/VW2/DU8 (floor-legality-proven, §7) and adapt for gfx90c —
   documented in the §8.6 S3 rows: keep the tile (geometry ports: gfx90c trades 64→7 CUs and
   4 MB→1 MB L2 for unchanged 64 KB/CU LDS + higher relative per-CU LDS headroom, so the padded
   variant is *more* at home here than on gfx900), then (a) **LdsPadA=2** (the one-knob delta
   that has always tracked CC), (b) **WGM8/WGM4** variants (CC's real lever), (c) **GSU2 +
   workspace** (MultipleBuffer; validator-legal, AMD-never-shipped), (d) **PGR=0** (VGPR-bound
   residency, §14.3).
   **DECKED, minus (c)**: pads A/B {1,2,4} + WGM8 + PGR=0 + GLVW=1 variants all
   emit on the steal tile (see `PLAN_BATCH`); **(c) is withdrawn — gate-refused
   on this port (§13.5 supersession)**.
4. **Group C on CC/ZZ winners, ranked probe order** (already forwarded + gated): pads {1,2,4}
   → **GSU>1 (MultipleBuffer)** → **PGR=0** → **NLCA=3** (§13.5 resolution plan; each also feeds
   the residency levers above).
   **DECKED, re-ranked**: CC/ZZ pad rows (A/B ∈ {1,2,4}) on the winner geometries; ZZ pads sit
   on the du8 tile only (the 32x32x16 winner is LDS-budget-full at the truthful 16 B/element);
   PGR=0 rows on CC/ZZ winners + SS/HH wide tiles; NLCA=3 only on the 3-load 96x96x16 tile
   (SS + HH); GSU>1 removed (see §13.5).
5. **Narrower reserve:** single-buffer LDS / DirectToVgpr probes on S/D wide tiles *only if* GSU
   fails to close an M2 cell (they free LDS, not VGPRs — §14.3), and TT 4x8/4x4 variants for the
   VGPR-bound wide cells at small shapes.
   **DECKED (partial)**: PLR=0 single-buffer + GLVW=1 rows on the wide SS tile emit; DirectToVgpr
   is not forwarded by `_write_phase_config` (stripped by `_strip_not_forwarded`) and stays out;
   the TT 4x8/4x4 small-shape variants are covered by the existing SS ladder (32x64x8/4x8,
   64x64x8/4x4).
6. **Halo/extension-only cells (8):** keep native-only; floor cannot pressure them.

### 14.6 Research-informed routes (2026-10-09)

The web-research pass (subagent, 2026-10-09) landed **`kernel_tuning_research.md`** —
GCN5/gfx90c hardware model, LDS bank-conflict math, occupancy/wave-quantization theory,
Tensile knob mechanics, complex-GEMM strategies, and SOTA cross-SKU porting/autotuning, all
URL-cited. Two route-level takeaways belong here (derivations live in the research doc):

- **Split-complex** (decompose CGEMM/ZGEMM into 3–4 real GEMMs + combine, the rocBLAS
  pre-MFMA strategy) remains the standing escalation *if* pads+GSU+PGR stay under ~2× on CC/ZZ —
  the "complex wall is memory/occupancy, not ALU" mechanism (§7, §13.5) says native-complex can
  still win via residency before we go split.
- **Don't copy the floor — transfer the principle.** Cross-SKU tuning research says tuned
  configs don't port, but tuned *regimes* do (occupancy band, tile∝1/bpe, VW@16B, GSU for small
  shapes). Our deck already embodies the regimes; the floor's remaining edge is same-kernel
  knife-edge ties (clock/noise, §14.2 classes 1–2) and one direction pick (CC:256) — which is
  exactly what the plan above targets.
