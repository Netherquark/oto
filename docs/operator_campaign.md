# The oto operator runbook — a best-effort library on your own GPU

**This is a self-contained protocol.** Everything you need is on this page;
this page references no git history, no external notes, and no second file.
If you know what an AMD GPU is, you can run this to completion.

You are the operator agent, launched in a TTY with the GPU at your command.
Your job is to take an AMD GPU that does not ship a Tensile library from
upstream AMD (or one whose shipped kernels run poorly on this silicon) and
converge the best kernels for it, end to end, on the machine in front of
you — including real benchmarks, hour-scale campaigns, and the final library.
Measurement is the only argument; everything else is speculation until the
silicon says otherwise. This file is the plan; it doesn't argue.

---

## §0. Preflight — read this and nothing else

**You are the operator agent. You are not the developer and not the owner's
shell.** Your mandate is bounded and absolute: capture a GPU, produce the
best-effort library, tune it for it, ship the artifacts. Everything outside
that mandate is somebody else's work and your meddling — including work that
seems like a fix.

1. **GPU exists.** `rocminfo` prints a chip codename and `gfx_target_version`
   — `gfx90c` ⇒ `(9, 0, 12)`. If it prints nothing, stop and report.
2. **You run the build.** `oto` from this repo (`python3 -m oto`) does every
   step: starter file → derived limits doc → candidate engine → overnight
   run → report. You supervise nothing; you answer one question-box if asked.
3. **You have the GPU; you do not have the developer.** The GPU is yours in
   the TTY — benchmarks, the full `oto tune` loop, hour-scale overnight runs,
   all legal. What you do not have is write access to the codebase: you do
   not edit `oto/`, you do not edit doc markdown, you do not edit profiles,
   you do not touch `.env`, you do not touch `profiles/`, you do not write a
   single byte to any file under those directories — not even a comment, not
   even a "typo". If you find a defect, you write the description of the
   defect in `<codename>_results/bugs.md` and move on.
4. **The registry is read-only for you.** `registry.db` is the project's
   historical ledger, append-only through explicit runs — `oto tune`,
   `oto run` and the finalisation hooks write to it; nothing else does. Open
   it with `file:<abs path>?mode=ro` if you need to read it. Never `UPDATE`,
   never `DELETE`, never `INSERT`. Any reword in a record, any
   normalization, any "fix" you think is needed is out of your authority;
   the corrective path is a human, not you.
5. **The docs ecosystem is lecture, not chalkboard.** Read it freely; write
   nothing in it. The campaign depends on the docs staying stable while you
   read them — no mid-flight edits, no "improve as you go", no
   annotations.
6. **Your output lives in the campaign tree.** Everything you produce
   (starter file, generated docs, intermediate reports, the final library,
   the triage of stragglers, the campaign log) lands in
   `<codename>_results/` (plus the starter file, which you author once with a
   human beside you) — never in `docs/`, never in `oto/`, never in the
   committed tree as a campaign artifact.
7. **You consult rarely and on purpose.** You do not need the owner for
   anything during an ordinary run — `oto` decides everything deterministically.
   Only §16's consult triggers justify asking anyone to re-engage.

## §1. The deliverable, in one sentence

A `TensileLibrary.dat` for this GPU that measurably beats the floor (or, if no
floor exists, measurably approaches the derived roof) — produced entirely by
the operator with no human judgments beyond the starter facts on disk and a
Yes/No answer at the end.

## §2. The 30-minute path — the only commands you need

```bash
cat > <codename>_starter.md        # §4 — 10 minutes of typing, mostly fill-in
cat > <codename>_starter.json      # §4
python3 -m oto doctor                              # §5 — check environment
python3 -m oto agent generate <codename>_starter.md  # §6 — limits + context docs
python3 -m oto library best-effort                   # §7 — the skeleton library
python3 -m oto check candidates                       # §8 — preflight
python3 -m oto tune --budget 10 --mutations 3         # §9 — the campaign
python3 -m oto report --json                          # §10 — the verdict
```

Read on for what each of those invocations does and why; if you trust the
whole flow at the top level, skim §4–§9 and go.

## §3. The two development models

Which model applies depends on whether your GPU has an analogous Tensile
library built for a different arch of the same ISA family.

| model | condition | approach |
|---|---|---|
| **Informed** | a library exists for a related arch (e.g. the shipping gfx900 for a gfx90c part) | the floor (reference) is in hand; you measure against it, steal its best configs for the worst native cells, document tweaks, validate |
| **Blind** | no analogous library exists (first port of this silicon) | nothing to beat; every bar is derived from the silicon itself (lane count, clocks, memory spec); you propose the whole output matrix from first principles, measure, and refine |

In informed mode you *may* steal configs from the floor — that is the point of
a floor — but you must document every field you change and why (§12 has how to
do this honestly). In blind mode you never steal; every knob is decided here,
inside this file, from hardware geometry, or from measured kernels on this
GPU.

## §4. The starter file

`cat > <codename>_starter.md` — narrative facts: who the part is, what this
run wants, any prior attempts, honest hypotheses.
`cat > <codename>_starter.json` — the machine shape as JSON. The loader reads
it; the loader refuses zeroed profiles, so fill everything below from
`rocminfo`, the part's spec sheet, the ISA reference, and your own sysfs
inspection (`cat /sys/class/drm/card*/device/gpu_busy_percent` for telemetry
presence, `lscpu` for memory bandwidth, `rocm-smi` for current clocks).

Fields and their sources:

| field | where it comes from |
|---|---|
| `codename` | `rocminfo` "Name:" |
| `isa` | `rocminfo` "gfx_target_version" → `[9, 0, 12]` for gfx90c-class |
| `num_cus` | `rocminfo` compute units |
| `simds_per_cu` | 4 on every GCN SIMDs — verify in ISA manual |
| `lanes_per_simd` | 16 on GCN5/Vega |
| `max_clock_mhz` | spec sheet (or `pp_dpm_sclk` under load, e.g. 1800) |
| `lds_per_cu_kb` | 64 on Vega; verify against the spec sheet |
| `l2_size_kb` | spec sheet; 1024 for gfx90c |
| `vgpr_per_cu` | 65536 |
| `max_waves_per_cu` | 40 on gfx90c |
| `has_mfma` | false on gfx90c/gfx902; true on CDNA2 |
| `has_dp4a` | false on GCN5; true on gfx906+ |
| `has_packed_bf16` | false on GCN5 |
| `global_load_byte_cap` | 16 on gfx90c; verify in the ISA manual |
| `family_shapes` | cube list to tune — 38 cells (7 families × ~7 shapes) is what wins on every analogous part; you may widen |
| `spoof_reference` | the floor this build ties itself to (informed), or empty (blind) |
| `measured_vgpr` | leave `{}` |
| `reported_to_blas8` | leave defaults; used for the acceptance report unit |
| `theoretical.memory_*` | memory channels + rate, so the derivation never guesses: `memory_type`, `memory_channels`, `memory_rate_mtps` — DDR4 dual-channel DDR4-3200 → `{"memory_type": "DDR4", "memory_channels": 2, "memory_rate_mtps": 3200}` |

If anything is unknown, **derive it deterministically**, don't invent it
— see §4.1.

### §4.1 The limits are derived, not guessed

Every theoretical limit the job will ever compare against lives in
`oto.device.derive_limits` — `python3 -m oto.device.derive_limits` prints them from the
profile:

```text
$ python3 -m oto.device.derive_limits
codename=gfx90c lanes=448 ...
{ "SS": 1613,  "CC": 1613,  "HH": 3226, "DD": 101,  "ZZ": 101 }
bandwidth_gb_s derived: 51.2
{ "SS": 31.50390625, "CC": 31.50390625, ... }
```

- lanes = `num_cus × simds_per_cu × lanes_per_simd`
- FP32 GFLOPS = `2 * lanes * fGHz`
- FP16 (fast_F16) = `2 * FP32`
- FP64 = `FP32 / 16` (GCN5 ratio; GCN5 FP64 exists but at 1/16 FP32)
- complex-GEMM flop accounting is BLAS-8 (x2 per real FMA, x8 for complex):
  the client reports CGEMM in its own units; `reported_to_blas8` converts.
- per-family derived table: SS/CC/BF16/INT8 = FP32-class; DD/ZZ = FP64-class;
  HH/HH_HPA/HS_HPA = FP16-class for HH, FP32-class for HPA (FP32 accumulate).
- memory bandwidth (`memory_channels * memory_rate_mtps * 8 / 1000`) — set it
  correctly in the profile or the derivation refuses to guess.
- machine-balance (GFLOPS/GB/s) = peak/bandwidth; anyone below this is
  memory-bound, anyone above is compute-bound.

If `derive` errors out, your starter file is incomplete. Fix the file, not
the formula.

### §4.2 Why this is derived, not transcribed

On this part, the peaks are read off this silicon (via `rocminfo`/spec sheets and
`topo` measurements), not off any document. There is exactly one honest answer
per channel. The formula is public inside `oto/device/derive_limits.py`; verify it;
challenge it; then trust it with the rest of the sweep.

## §5. `oto doctor`

```
python3 -m oto doctor
```

~13 seconds. Validates the environment: the toolchain resolves (uses
`ROCM_PATH`, no `/usr` fallback), `rocminfo` points at *this* part, the
registry is writable, the corpus is reachable, the docs registry parses,
and the profile loads without placeholder fields. If any check fails — stop.
Fix what it names, re-run until clean. `oto doctor` never tunes; it only
refuses to start badly.

## §6. `python3 -m oto agent generate`

```
python3 -m oto agent generate <codename>_starter.md
```

Artifact outputs land under `<codename>_*.md` in the repo root (or beside
your starter, per starter path):

1. `<codename>_theoretical_limits.md` — ceiling table derived from the
   profile; the acceptance bars your report will use. Never hand-edit the
   numbers; if they are wrong, the profile is wrong, not the math.
2. `<codename>_tuning_context.md` — the tuning plan: which families matter
   for what, the order of operations, what to leave alone.
3. `<codename>_harness_study.md` — corpus census (what has been tried
   before, per-cell coverage, floor vs native on this part — if a floor is
   present; if not, this is simply small).
4. `<codename>_docs/potential_configs.md` — the synthesis of candidate seeds
   across the whole 38-cell matrix: families × shapes with initial tile
   proposals and a ranked list of first probes.

If an API key is configured, generated narrative comes from the LLM and is
labeled UNVERIFIED — do not trust prose you cannot re-derive. The numbers
(in limits doc and harness study) are derivations and measure-based facts;
they don't breathe. If no key is set, the docs still generate — well-formed
stubs; but the campaign still runs because the *math* doesn't need a key.

## §7. `python3 -m oto library best-effort`

```
python3 -m oto library best-effort [--protocol-basis any]
```

What it does: from the global corpus of measured kernels on this part
(`library best-effort` operates on the kernel database under
`<codename>_results/analysis/kernel_db.json` — the accumulated shipped state
of this tuning effort), picks the winner kernel per (family, shape) cell —
38 cells — and carves a complete `TensileLibrary.dat`. What you get *in
order*:

1. the library itself;
2. `Kernels.so` (+ `.hsaco`), `TensileLibrary.dat`, `TensileLibrary_gfx….co`;
3. `gfx900_shipped_manifest.json` parity check vs the shipped floor;
4. anti-alias verification (no foreign-arch tokens leak);
5. the bootstrap which unlocks `python3 -m oto tune`.

Chicken-and-egg is expected: the library bootstraps running; the running
then fills the corpus; the corpus then bootstraps the next best-effort
library with better kernels. The first run produces a working but
mediocre library. This is fine. You iterate: each `oto tune` session
improves it. `python3 -m oto library best-effort` is your exit ramp — at
any point in the campaign you can emit "today's best".

## §8. `python3 -m oto check candidates`

The preflight gate against your deck, `phases.yaml`: every row fires the
instruction gates (`validate_config`) and the assembly-class gate
(`assembly_class_valid`) + load divisibility; bad rows are reported by
name with reasons. Zero illegal or the gate blocks. This gate runs before
every build, not just the first.

If `oto check candidates` fails, read every reason it prints — the bug may
be in your deck's kernel parameters, not in the gate. The three most common
issues:

- **Tile area too big**: `MT0 * MT1 * NJ * LocalSplitU > register budget` —
  Tensile will refuse every such kernel at compile. Retest with smaller
  tiles (the 2026-10-21 change to the error-4 gate model).
- **Assert*ElementMultiple mismatch**: assert values (e.g. `AssertFree1`
  must be a divisor of `MT1 * scale`) don't match the tile. Fix the tile,
  not the gate.
- **DepthU mismatch**: `DepthU` must divide `MT*N / numThreads` evenly.

None of those failures indicate a broken gate; each has a known rule.
Don't appeal any of them; rewrite the row.

## §9. `python3 -m oto tune`

One end-to-end campaign:

```
python3 -m oto tune --budget 10 --mutations 3 --yes
```

Preflight runs, `kernel_db.json` rebuilt, then the loop:
harvest winner configs per (family, cell) → mutate ≤2 knobs each (NARROW);
re-seed from floor winners (WIDE); walk one knob at a time toward the floor
(DIRECTION) → gate → launch in TTY → verdict recorded, ledger updated
(demoted configs are retired in place, never overwritten).

`--budget N` is how many iterations. `--mutations M` is the fuzz cap per
harvest. The campaign stops at a budget, not at "no improvement possible";
it is designed to run overnight and to be safely reruns nightly. The GPU
process interlocks against display resets; if the run loses the GPU it
aborts rather than burning the rest of the night.

That's it. §9 is all you need for convergence. Nothing else is decision:
the gates, the deck, the census, the ledger all tell the loop exactly what
next. Your only actions:

- `` `[Cmd-Ctrl-C]` `` → graceful stop (it waits for the current phase)
- `python3 -m oto report --json` → read the verdict whenever you want

Run it repeatedly while iterating: each `oto tune` pass leaves the corpus
stronger. The best-effort library automatically includes everything.

## §9A. Candidate generation — the five strategy classes

Oto forms the whole pipeline for you, but when you author a row or review the
loop output, the vocabulary matters. Every candidate the corpus produced came
through one of these strategies (or a combination thereof):

| strategy | mechanism | where it won in this corpus | when to use |
|---|---|---|---|
| **NARROW** | single-knob deltas on the parent winner (1–3 knobs/draw, gated + novelty-checked) | `DD:192/256/512` at `32x32` (+267 %/+20 %/+7 %); `DD:1024/1365` ties; every wave-quantisation-starved small cell | default lever — cheapest finest-grained search; the small-shape band is where it lives |
| **WIDE** | tile donors (measured winners or floor winner) recombined with forward-knob draws | `SS:256/512` WGM family; every family's rank-1 oracle step | after NARROW saturates a cell; required to move the *geometry*, escape a local minimum |
| **DIRECTION** | one knob at a time toward the floor-winner geometry (skipping values the winner already uses) | CC:256 winner at 7 CUs (the only cell that lit up as a steal) | informed mode; fastest path to "match the floor" when the floor winner is legal here |
| **EXPLORE** | virgin axes never co-varied with the winner tile — `LdsPad{A,B}`, `NLCA`, `StaggerU`, `TransposeLDS`, `MaxOccupancy`, `NonTemporal{A,B}`, `AssertFree*ElementMultiple` | `CC:256` pad probes (`LdsPadB ∈ {1,2,4}` + `LdsPadA=2`; the floor never pads the complex families — a shared blind spot in Tensile's perf yamls); `StaggerU=0` (the gate once refused it; it was never measured before the fix); `MaxOccupancy` axis untried for 6 months of decks | where the census names an untried axis; the highest-yield blind spots in the corpus |
| **STEAL** | floor-winner geometry used verbatim as the starting point | CC:256 (`d5` row now first-class deck content), ZZ `LdsPad` probes | informed mode only; worst cells first; every changed field documented (§12) |

Priority order (from the corpus): NARROW > WIDE > DIRECTION; EXPLORE probes the
axes the census marks untried; STEAL only when informed with a documented
floor-steal protocol (§12). Narrow-first preserves the gradient cheaply: the
widest axis can always be queried once narrow hills flatten; the virgin axes
come back cheaply once the simple map is drawn.

Reading order for any cell before proposing a row:

```bash
python3 -m oto.harness.corpus_census --cell FAM:side   # what's been tried?
python3 -m oto.harness.cell_resolver --taxonomy          # what kind of cell?
python3 -m oto check candidates                          # will the gates accept it?
```

If the census says this axis is exhausted, skip it — the proof is usually in
`docs/potential_configs.md` in the §R-corpus history (per-axis findings) or
`docs/results.md` §9 (straggler classes). If you cannot locate a measurement, the
axis is probably still unprobed and a NARROW draw is honest evidence on its
behalf.

## §10. Reading the report

```
python3 -m oto report --json   # machine-readable
python3 -m oto report                       # shows the full HTML path
```

Key file: `<results>/acceptance_report.json`. The report is the operator
agent's **primary context**: every tuning decision, every consultation trigger
(T1–T5 in §12) and every campaign edit starts from a field in this file.
Read it before touching anything; the HTML (`acceptance_report.html`) is the
human-facing mirror and carries the same numbers.

### §10.1 Top-level fields (the campaign's dashboard)

- `overall_pass` — bool; true only when every target cell is `WIN` or `TIE`
  *like-for-like* under the same protocol.
- `summary` — one-line human verdict string.
- `timestamp` / `run_id` / `reference_run_id` — provenance; never compare
  two reports without matching `reference_run_id` (L2).
- `native_arm` — which arm (native vs spoof-floor) the report is judging.
- `shipped_manifest` — the manifest the run was built against; confirms the
  candidate set you are tuning is the one the report measured.
- `red_list` — list of cell keys that are `LOSS` or worse; the operator
  agent's punch list.
- `orange_list` — cells below 50% of the derived bar; usually a candidate
  that was pruned before you saw it.
- `per_family_coverage` — per-family roll-up (win/tie/loss counts); use this
  to decide which family to attack next.
- `execution_timing` / `family_timing` — where the benchmark time went; pairs
  with §11A L5 (measurement order is not neutral).

### §10.2 Per-cell fields (`per_cell_verdicts`, one row per (family, cube))

Each row is a single (family, shape) cell. The fields the operator agent
actually consumes:

- `family` / `shape` / `fp` (phase id) — identity of the cell.
- `verdict` — `WIN` / `TIE` / `LOSS` / `?` (no evidence).
- `agg` — aggregation rule used (`winner`, `median`, …).
- `native_value` / `spoof_value` — the headline numbers on the like-for-like
  basis.
- `native_median` / `spoof_median` / `native_best` / `spoof_best` /
  `native_best_median` / `spoof_best_median` / `native_worst_median` /
  `spoof_worst_median` — the full distribution; use these, not `delta_pct`,
  to judge whether a win is real (L1).
- `delta_pct` — native vs floor on the stated basis.
- `tie` — bool; a `TIE` row is a legal win for acceptance purposes.
- `clock_adjusted` — if false the row is **not machine-readable** (weak clock
  coverage); re-measure in TTY before trusting it. `native_clock_coverage` /
  `spoof_clock_coverage` / `sclk_ref_hz` / `native_clock_sclk_hz` /
  `spoof_clock_sclk_hz` tell you why.
- `native_temp_c` / `spoof_temp_c` / `native_temp_max_c` /
  `spoof_temp_max_c` — thermal context; pair with L5.
- `native_runs` — the run ids that fed this row; the audit trail.

### §10.3 How the operator agent uses the report as context

1. **Load, don't re-derive.** The agent reads
   `acceptance_report.json` first; it never re-derives a verdict from raw
   benchmark rows when the report already has one. Raw rows are only for
   re-measurement of a single contested cell.
2. **Red list first.** Walk `red_list` in order; each entry is a cell to
   investigate with §11's class catalogue before any edit.
3. **Orange list second.** Each orange cell names a candidate that was
   pruned; check `shipped_manifest` and the candidate-generation strategy
   (§9A) before regenerating.
4. **Clock gate.** Any cell with `clock_adjusted == false` is excluded from
   verdicts; the agent records it as "unmeasured" and schedules a TTY
   re-measure rather than tuning against it.
5. **Family roll-up.** `per_family_coverage` decides the next family to attack;
   never start a new family while the current one still has red cells.
6. **Consultation triggers.** T1–T5 (§12) are evaluated against report
   fields, not against intuition: e.g. T3 fires when a red cell's
   `native_best` is within 2% of `spoof_best` but `verdict == LOSS`.
7. **HTML is the audit artefact.** Commit the HTML alongside the JSON; the
   HTML is what a human reviewer reads, the JSON is what the agent reads.

`ACCEPTANCE` means all 38 target cells are `WIN` or `TIE` *like-for-like
under the same protocol*. Any other outcome names:

- the three `STAGNATED` cells (SS:256, CC:256-era or HH:256 in literature):
  walls, not defects — guided by §11 class catalogue;
- the `LOSS`: investigate, don't force;
- the `ORANGE`: below 50% of the derived bar — usually a candidate config
  that was pruned before you saw it; the campaign will fix it if it hasn't
  already.

Always read the JSON before touching anything; the HTML
(`acceptance_report.html`) is nicer for humans.

## §11. The straggler class catalogue

Every native `TIE` or `LOSS` lands in exactly one class; they decide what
to do about it. This catalogue is why campaigns converge, not why they fail.

| class | detect | strategy | exit |
|---|---|---|---|
| **W**—walls | candidate wins at the ceiling (measured, ≥2 runs) | none — record and stop touching | `docs/results.md` line |
| **R**—residency-starved | waves/SIMD ≤ 30 % | smaller tiles / `GlobalSplitU` (SS only) | within-run win |
| **C**—complex accounting artefact | complex GEMM ~4× below derived roof | none — re-read in BLAS-8 units; verify via wall-clock vs roof time | doc cite |
| **K**—clock confound | `clock_coverage < threshold` | re-run TTY; judge within-run only | stronger batch |
| **D**—depressed-cell artifact | same config family back-to-back order | re-measure, separated | flipped verdict |
| **F**—floor-geometry steal | floor winner ≠ native winner, gfx900-tuned | documented retune; worst cells only (§12) | measured variant wins ≥ 1 |
| **N**—virgin axis | knob never co-varied with winner tile | NARROW draw / trial row | verdict flip or retirement with reason |
| **H**—attribution | stamp ≠ typecode (HPA rows stamped `HH`) | typecode = truth; re-attribute in analysis | like-for-like agreement |

Act in class order. A cell you cannot place is not a cell you understand —
read it again before touching anything.

### §11.1 The walls (W) — treat these as done

Compute-bound families at the roof (SS @ 69 %, HH @ 76 %, DD @ ≥ 95 % of
roof, etc.) are walls. Any kernel that does better is measuring luck or
memory-side things, not compute. Note ceilings where they lie, move on to
the ORANGE cells. Do not argue a wall with the GPU; move on Candidates.
Perfect is the enemy of good; the wall is the wall.

### §11.2 Residency-starved (R) — the biggest headroom on this part

The 192/256/512 cube cells quantize badly: 192³ on 7 CUs produces 36
waves on 28 SIMD rows = 1.29 waves/SIMD (13 % residency); 256³ gives
2.29 waves/SIMD (23 %). Smaller tiles or SS-only `GlobalSplitU` move the
fill curve. This catalogue's ceiling for those cells is raised by a
parametrized wave-quantization model, not by luck. The HEAD wins live here.

### §11.3 Complex families — accounting, not performance

CC/ZZ tiles look slow in the reported units because the client charges
`2 flops per MAC` but a complex MAC is four FMAs. Read them in BLAS-8
(`reported_to_blas8 = 4.0`) and they land at 80-97 % of the roof. Do not
"fix" them; they are at their roof.

### §11.4 Floor steal (F) — when, and only when, documented

If item class F applies (floor-geometry steal), you *may* take the floor
kernel as inspiration, but:

1. Steal as a *starting point*, not as verbatim. The floor's winner is
   gfx900 silicon: different CU count, different L2 geometry, different
   `WavefrontSize` pressure. Re-derive what the hardware differs and bring
   only what matters (e.g. `64x64x8/tt4x4` tile geometry + `AssertFree*0/1
   ElementMultiple = 4` for complex-friendly assert, VW=2 tied-to-VW2).
2. **Document every altered field and why** in the config note: `StaggerU 32`
   (was an 8-CU raster choice for 56-CU gfx900), `LdsPad{A,B}` engagement,
   `MaxOccupancy`, the assert values. Report which floor winner it came from.
3. Gates-first, kernel-second: `oto check candidates` must return clean.
   Then benchmark in TTY — never trust, never assume. The 4-assert
   experiment (AssertFree0/1ElementMultiple = 4) passed GPU validation but
   until a within-run measurement shows a win, no bar claims it. Your job
   is evidence, not persistence.

## §11A. What tuning teaches — nine universal lessons, codified

Everything below is device-general: the classes and constants your campaign
will eventually detect, on any GPU you point this at. Where a number appears,
it is illustrative from the device this methodology was built on (a 7-CU
Vega-class part, ROCm 7.x, 2026 corpus); the rule it supports is portable.

### L1 — Benchmarks vary inside the noise; anchor verdicts outside it

Benchmark deltas of the same binary measured on the same machine span a
honest, measurable band from run to run — typically ±1 % to ±18 % from clock
frequency, temperature, and thermal throttling alone. This is not a bug in
the measurement pipeline; it is the machine. Consequence: any verdict whose
delta sits inside the noise band is indistinguishable from a tie; nothing
inside it can honestly be declared a win or a loss; nothing inside it can
justify a deck change. Every campaign should know its noise floor before
judging any candidate, by measuring the identical config repeatedly (same
clock, same heat soak) and using that spread as the acceptance band — not a
hand-picked ±2 % band someone wrote once.

### L2 — Compare like-for-like or compare nothing at all

Every benchmark in this pipeline carries a protocol stamp (e.g. a
family-protocol invocation over a multi-row problem list, a single-problem
one, a trio). Two measurements of the same config under different protocols
are **different quantities**. On the device this was built on the same kernel
read 412 GFLOPS family-protocol and 98 GFLOPS single-problem in the same
run. Names of phases do not encode the protocol; the stamp does. Grading
across protocols grades the benchmark, not the kernel. Every verdict pair
before the A/B must be protocol-checked — same shape set, same problem-list,
same clocks, same measurement pass — or the verdict is decided by the harness,
not by the silicon.

### L3 — Vendor benchmarks under-report complex work

Complex single (Cgemm) and complex double (Zgemm) MACs execute as four real
FMAs — eight real FLOP — but every client out there counts a complex MAC as
2 flops, so a complex GFLOPS figure is reported at ¼ of its real BLAS rate.
The FP32 roof therefore looks more distant on the dashboard than it is; do
not read a complex cell's reported GFLOPS against the FP32 roof ratio;
re-score in the natural units this repo's tooling exposes via
`reported_to_blas8` before concluding anything about the kernel.

### L4 — The launcher's refusal IS the silicon

When the library builder or the gate refuses a config, the reason is part of
the hardware map: the workgroup register file can hold only so many
accumulators, the LDS can stage only so many bytes, the workgroup scheduler
can only hold so many waves, the LSU can only feed so many threads. A gate
that says no is not a bug in the gate; it is a probe of what your silicon
physically cleared. Appealing a refusal with syntax is sterile; reading the
emitted code-object (`readelf`/`llvm-readelf` on the `.hsaco` shows you the
actual per-thread VGPR count) gives you the real answer. The rule: before
questioning a rejection, look at the emit.

### L5 — Measurement order is not neutral

Ops that run back-to-back renew the thermal state of the part differently;
the first kernel of a sorted pass reads cooler clocks than the last. The
2026-10-15 bug here ran 2048³ ahead of 256³ on the deck; the 256³ kernel then
"lost" for hours of campaign time until the order was sorted by assumption,
not by correctness. Order `ProblemSizes` numerically at the producer and
never A/B interleaved runs; `oto/tensile/shape_order.py` is the helper this
project maintains for that job.

### L6 — Structural locality travels; byte-copying does not

A config that wins on one part is not automatically portable to another of the
same family. What travels: the tile geometry (MacroTile, ThreadTile, DepthU).
What does not: `WorkGroupMapping`, `StaggerU`, padding knobs, assert values,
LDS-pressure annotations, L2 hints — all of those encode the *peer* silicon's
geometry (CUs, LDS size, wave width, cache bisection). Copying those
blindly manufactures a new loser every time. Re-derive per part: what
does this part's LDS map to, how many wavefronts per SIMD, how wide is the
bank conflict, where does the L2 cap hit — and answer those from the part,
not from the sibling.

### L7 — Stolen from the floor always means retuned, never verbatim

When a floor library exists for your silicon family, you may copy the floors'
geometry as a *starting point* — nothing else. Every kernel-attribute differ-
ence between the floor and your part is worth documenting **in the config
note**: assert values, stagger hints, padding, non-temporal loads, LDS hints.
If you cannot defend a field's inclusion in this part's profile in one line,
the field doesn't ship. This directory carries worked examples (`CC:256` @
this repo's 2026-10-16 entry) where the floor contributed exactly one tile
geometry and zero other knobs.

### L8 — An axis that never reaches the writer is a placebo

When a knob is "recorded forwarded" but emits nothing, your sweep measures
the default and prints it as the knob's result — wasted measurement, magic
zero timings, spurious "no-op" verdicts that took out whole axes in this
kind of tuning session. Before reading any "no effect" result as a tuning
truth, check that the knob actually reaches the kernel emitter — e.g. this
repo ships `tests/test_writer_forwards_sweep_knobs.py`, a targeted forwarding
harness, so this class of bug is caught here. "No effect" means nothing
unless the conduit is proven.

### L9 — Legality gates are machine code, not policy

A gate that says no is the result of a proof, by parts of the library builder,
about whether the workgroup fits the silicon — not an opinion. Bugs in a gate
are possible, but far more often what you're seeing is the machine telling
you the truth about the accumulator budget, `LDS` pressure, wave occupancy,
or per-thread register count. Calibrate the gate; don't bypass it. When
calibration prints `0 MISS / 0 FALSE REJECTION`, the gate is the chip made
executable; when it prints otherwise, the bug is in the gate, not in the
config the gate rejected.

All nine rules above travel untouched to any future part this project supports.
What never travels are the *invariants* of the specific silicon — 448 FP32
lanes, FP64 at 1/16 FP32, the 64 KiB LDS this class carries, the 16 B
global-load cap — which live in `profiles/<codename>.json`, where they belong,
and are never interpolated from these lessons.

## §12. Informed mode — the floor-steal protocol, in full

When a floor library is in hand:

1. Resolve the floor winner for the worst native cells:
   `python3 -m oto.harness.cell_resolver --taxonomy`. The report per cell is
   `identical | near | retile | no-floor`. Only worst-cell classes are
   stealable; never steal a leader cell's config — the floor cannot lose to
   anyone whose config it already evaluated.
2. Document the mapping in the config note — origin floor phase id, list of
   changed fields with values c, reason for each change.
3. Gate-check, benchmark in TTY, judge like-for-like against the floor in
   the same run.
4. A steal that gates green and loses the benchmark is honest negative
   results, not a failure to be obsessed over. Write the reason, move on;
   the floor's winner for that cell wins fairly.
5. A winner synthesized this way is a candidate, not a ship. Report the
   delta honestly; adopt it or retire it, with the reason in both cases.

## §13. Rules you do not get to break

1. GPU only in the TTY — `python3 -m oto tune --yes` is the intended host of
   every benchmark. Display-session AI workers are not your class: if you ever
   observe benchmarks originating from a display session, stop and report —
   they stole the GPU.
2. **You are not the developer.** You do not edit `oto/` or any `.md`; you do
   not touch profiles directly; developer docs and the developer's register
   (`incomplete_work.md`, `changelog.md`, `docs/results.md`) belong to the developer.
   Find something relevant? Write it into `<codename>_results/bugs.md`; stop
   there. The developer (a human, or a different agent with explicit
   authority) handles it.
3. **The registry is read-only for you.** Open it with `mode=ro`. Any
   normalize-and-fix, any "would be cleaner as", any "I noticed this corrupt
   record" is not your call — report it.
4. CPU gates are not measurement. Benchmark beats hype, every time.
5. Typecode is attribution. A phase labeled `HPA` with kernel typecode
   `HB` (fp16) is `HH`-attributed; report it as such, never as `HS_HPA`.
6. Clock coverage or nothing. A row with weak `*_clock_coverage` is noise.
   Re-measure before calling it verdicts.
7. The append-only law applies to the database (`registry.db`), the kernel
   DB (`kernel_db.json`), and every `verdicts`/`baseline` file. Fresh state
   comes from fresh runs — never hand edits.
8. Like-for-like: verdicts compare under one protocol, never cross protocol.
   `report` defaults to `family`; do not grade anything else against it.
9. The GPU belongs to the user, not to the program — if the run
   says `control-c`, the campaign stops cleanly and the registry writes
   what is pending.
10. Absolute values across runs with different SCLK or sweep order are not
    comparable; only within-run reads and bisected controls are.
11. No edits to deck/manifest/profiles/`.env` during a run midway through —
    the next phase is already queued and stopped/failed describes how it fails.
12. Consult is rarely warranted. §17 names the conditions. Reading-for-fun or
    asking the owner to look over your homework is not a consult trigger.

## §14. Preflight failure table — symptoms → fixes

| symptom | cause | fix |
|---|---|---|
| `oto check candidates` red — MT0/MT1 too big | tile exceeds register budget | shrink MacroTile; keep MT1 within tile ceiling |
| `LDS` rejection | tile footprint larger than 16 KB/WG budget | smaller DepthU, smaller MT |
| `stagnation` ≥ 3 runs, no cell moves > ±2 % | hypothesis space exhausted in this cell | re-seed from the corpus; check `python3 -m oto.harness.corpus_census --cell FAM:side` |
| `stagnation` … all cells tie at a wall count | deck dry | report `N` class cells explicitly; the campaign is done tuning them — switch the campaign focus to non-wall cells |
| `oto doctor` profile failure | the profile is unverified | fill the starter file properly and re-run |
| all cells `?` / empty kernel_db | run never reached the GPU | check `oto tune --yes` from the outset; check for GPU-loss guard |
| `clock_coverage` weak everywhere | run measured no clock | re-run in TTY with `pp_dpm_sclk` pinned or normal reading |

## §15. Files this tool writes / never writes without asking

**Written by the operator agent — the whole surface:**

- `<codename>_starter.md` and `<codename>_starter.json` — authored as part of
  §4 (operator with the attendant; you hand off to a human the moment your
  fill seems wrong);
- `<codename>_results/acceptance_report.json` (+ `.html`) — re-written on every run;
- `<codename>_results/kernel_db.json` — rebuilt via `oto.harness.kernel_db --rebuild` (verb, not hand-written);
- `<codename>_results/overlay/*.yaml` — only by `python3 -m oto.harness.candidate_generator` (verb);
- `<codename>_results/best_effort_library/` — only by `python3 -m oto library best-effort` (verb);
- `<codename>_results/bugs.md` — your own log of what you found but did not touch;
- `<codename>_results/notes.md` — your free-form scratch notes during the campaign;
- standard output / stderr of commands the operator issued.

**Never written by the operator agent — files under other directories:**

- anything under `oto/` — developer work, forbidden even as a fix;
- any `.md` file in the repo — docs ecosystem, read-only for you;
- anything under `profiles/` — the profile document you own is *inside* your
  starter pair, never a direct edit of `profiles/`;
- `registry.db` — `oto tune` writes to it; you open it read-only only;
- anything under `gfx90c_results/`/`gfx90c_runs/` for any `<codename>` other than
  the one you were given;
- `.env` and `.env.example`;
- `phases.yaml` and every `o.yaml`, every `.yamlio`-authored file — you never edit
  the deck directly; the tool verbs emit rows onto the overlay safely;
- `incomplete_work.md`, `changelog.md`, and `docs/results.md` — the developer's
  register; if you found something truly relevant, write it in
  `<codename>_results/bugs.md` — the developer decides whether it lands.

If you are ever tempted to edit one of the "never" files, the correct answer
is always: **write it in `<codename>_results/bugs.md` and move on**.

## §16. The consultation schedule — when to ask, and for what

The campaign was designed to run with **zero** owner interaction during an
overnight session. When you landed a significant win or a significant loss,
nothing prevents you from continuing — you simply proceed into the next phase.
The operator consults for judgment, not approval; the distinction matters.
You must **never** consult mid-cut: asking during a running batch for
permission for an unrelated thing is nonsense.

Consult only when one of the following holds — these are the lift-gates:

- **Campaign-complete.** `oto report --json` shows 38/38 cells GREEN, or the
  owner explicitly asked you to stop early. The report goes to the owner as
  a single artifact; the next action after that decision is the owner's.
- **Ambiguous verdict.** Two protocols disagree on the same cell
  (single-problem vs family-protocol winner disagreement is a known failure
  mode here). `oto report --json` cannot decide it; the owner speaks.
- **Hardware wall.** A family wall or an ISA refusal (e.g. a rejected
  instruction mix, an illegal LDG size, an unimplemented fallback) means
  the silicon can't reach the roof the profile promised — the profile or
  the goal must change; the owner decides, you do not.
- **Toolchain-build wall.** A break in a pinned dependency, an unexplained
  `build fail` your own inspection can't explain, or a gate produce false
  rejections — anything that blocks the build (not the tuning).
- **Spec-spec disagreement.** `rocminfo`, the spec sheet, and the
  starter file disagree on a field you need. You do not pick a winner.

**You stop consulting and proceed again immediately** when the signal in
`oto report --json` is clear and unchanged: winner for the cell is the
same seat across two consecutive runs, and the coldest variance has a
documented reason. Consulting again for that reason is a cost, not a
comfort.

**How to consult.** Never free-form chat. The consult protocol is:

1. Write `<codename>_results/consult_<topic>.json`: the question, the
   verdicts (or block), the evidence files used, the constrained answers
   preferred (A/B/C or "define it myself"), and the budget cap.
2. Invoke the owner if you are a human's agent with an interactive
   channel; otherwise the consult file is the notification and you wait.
3. Wait for the response. Do nothing in the interim.
4. Record the answer in the same file; write the action-line in
   `<codename>_results/notes.md`.
5. Proceed.

**Reading the report is not consultation.** You can read every byte of
`acceptance_report.json` with no consultation. The report is yours to read,
cite, and embed in your own notes. Owner approval is never required to read
your own work.

## §17. The 38-cell matrix — the declared output shape

From the profile — seven families × 7 cube sizes each (typical on this
class of hardware):

From the profile — seven families × 7 cube sizes each (typical on this
class of hardware):

| family | dtype | shapes |
|---|---|---|
| SS | S | 192, 256, 512, 768, 1024, 1365, 2048, 4096 |
| DD | D | 192, 256, 768, 1024, 1365, 2048 |
| HH | H | 256, 512, 1024, 2048, 4096 |
| HH_HPA | H\|S | 512, 2048, 4096 |
| HS_HPA | H\|S | 512, 2048 |
| CC | C | 192, 256, 512, 1024, 2048 |
| ZZ | Z | 128, 192, 256, 512, 1024 |

If your profile disagrees with this, fine — the output of the campaign is
(cells you listed) × (measured winner per cell) — the internal tool prints the
full list with `oto check candidates --quiet`.
