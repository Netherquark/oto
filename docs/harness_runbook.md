# harness — agentic kernel-tuning harness (CPU-only)
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


> **Scope:** harness machinery guardrails and candidate workflows. For the
> CPU-only command card, see [`docs/harness_runbook.md`](harness_runbook.md).

Polished, repo-homed home of the candidate-generation machinery. The read-only tools plus
this runbook give an agent (or a human) the ground truth needed to propose a
defensible candidate without re-reading the raw corpora. Nothing here ever
benchmarks or touches a GPU (CPU-only, never benchmarks). For the ecosystem
boundary, see [`docs/README.md`](README.md); for the CPU-only contract, see
[`claude.md`](../claude.md) §5.

## Layout

```
oto/harness/gate_calibration.py   # gate-vs-corpus agreement census (false rejections + misses)
oto/harness/failure_triage.py     # empty-phase reason census (why did a phase produce nothing)
oto/harness/rule_calibration.py   # probe a *proposed* rule in isolation (false rejections + catches)
oto/harness/kernel_db.py          # kernel_db.json builder (ground truth)
oto/harness/corpus_census.py      # corpus history: axis/geometry coverage + per-cell geometry history
oto/harness/regression_matrix.py  # regression_matrix.json builder (deck vs floor vs all-time)
oto/harness/cell_resolver.py      # per-cell winner resolver + cfg_gap (full knob surface)
oto/harness/coverage_map.py       # legal geometry space per cell + what the corpus measured in it
oto/harness/tensile_probe.py     # the legality oracle: Tensile's own verdict on a config
oto/harness/deck_probe.py          # the pre-run sweep: every unmeasured deck row through Tensile
oto/harness/coverage_graph.py      # the coverage graphs: the legal space, what is unexplored, the peaks and the traps
oto/metrics/report_coverage.py        # the report's problem-space coverage section (reads the figures' hand-off)
oto/tools/deck_review.py          # the three pre-deck questions (score/legality/flood)
docs/harness_runbook.md            # this runbook
gfx90c_results/analysis/kernel_db.json          # cache (rebuilt)
gfx90c_results/analysis/regression_matrix.json  # cache (median basis, per-family grid)
gfx90c_results/analysis/cells_resolved.json     # cache (winner map; cell_resolver)
gfx90c_results/analysis/cells_resolved.full.txt # same, human table (docs/gfx90c_tuning_guide.md §13 §3)
gfx90c_results/analysis/coverage_map.json      # cache (legal space + coverage; coverage_map)
```

Module list and ownership: see [`oto/README.md`](../oto/README.md) for the harness
modules (e.g. `oto/harness/*`). Both tools resolve families/shapes/dtype from the
repo's canonical sources (`oto.device.loader`, `oto.tensile.library_parity`) — they
can never disagree with the shipped grid (docs/gfx90c_knowledge_base.md §6.1). Cache paths are
listed above.

## The pre-deck questions

The corpus census comes first; `oto/tools/deck_review` then answers the three
questions in order. All are CPU-only and read-only:

```bash
python3 -m oto.harness.corpus_census --cell SS:1024   # what has already been tried?
python3 -m oto.tools.deck_review score            # is the floor actually beaten?
python3 -m oto.tools.deck_review legality         # is this knob domain deck-safe?
python3 -m oto.tools.deck_review flood --cap 24   # where is the GPU budget going?
```

**0. `corpus_census` — has this already been measured?** Read the cell before
choosing a knob. `--cell FAM:side` lists every geometry the corpus has measured
on that cell, the row count behind each, and the floor's best; `--family` /
`--typecode` print the distinct value and best seed-median for every structural
axis; `--knob` narrows to one. This is the empirical half of
`docs/gfx90c_tuning_guide.md` §13 §R41 (the axes the corpus has finished with); the
mechanism half is the gate. It reads `kernel_db.json` only and writes nothing
except `--json`. `--typecode HHS`/`HSS` (or the deck spelling `--cell
HH_HPA:1024`) is how the HPA blocks are read — they share family `HH` but not a
geometry history.

**1. `score` — never trust the headline.** The acceptance report grades on
`agg="winner"` = *best per-kernel median*, which is an **order statistic**: the
arm that draws more kernels has the higher expected max. The native arm carries
~28 configs per SS cell per run (~143 accumulated) against ZZ's 26-config spoof
arm, so a cell can read WIN while its *typical* kernel loses by half. `score`
recomputes the verdict under every basis `oto.metrics.ab_delta._stat` expresses
and prints the `floor_best` losers and `winner` ties, which is the actual work
list. Read `median` and `floor_best`, not `winner`.

**2. `legality` — never deck a domain blind.** Every (family, knob, value) draw
from `census_domain` — the device-truth set (global `FORWARD_KNOB_DOMAINS` ∪ the
family override), *not* the mutator's narrowed `forward_domain` — is classified
against the launch gates on the tiles
that *actually ran* (read from `kernel_db.json`), into three buckets: **legal**,
**coupled** (tile-dependent, ordinary), and **refused standalone**. Only the last
is worth reading closely, and even it is not "dead": `StaggerU=0` is refused
because `StaggerUStride` defaults to 256, and becomes legal the moment
`StaggerUStride=0` is drawn too. A genuinely dead value is one whose reason is a
structural class rule ("illegal on gfx90c", "no MatrixInstruction"). The reason
text names the culprit, so read it rather than the count. Use this after editing
`db_knobs.py`; `python3 -m oto check candidates` on the real deck — which sees every
knob at once — stays the authority.

**3. `flood` — know what the run is actually measuring.** The per-cell distinct
config census from `kernel_db.json`, plus what a top-K cap would retain and
whether that cap loses any cell winner. A cell whose median is a fifth of its own
winner is a cell in which almost everything measured was junk. The cap is ranked
by measured median, so it retains every cell's frontier by construction — which
`tests/test_deck_review.py` asserts.

## Workflow

### 1. Rebuild / refresh ground truth

**Automatic (the normal path).** `kernel_db.json` self-refreshes whenever a run
reaches a data-producing terminal status (`completed` / `interrupted`): the
registry's `update_run_status` choke point calls the rebuild best-effort, so the
cache is always fresh for the next mutation without a manual step. It is
disabled with `OTO_NO_AUTO_KERNEL_DB_REBUILD=1` (seq runners that manage their
own timing) or the `SQLiteRegistry(..., auto_rebuild_kernel_db=False)` flag
(tests). A failed refresh is logged to stderr and never fails the run.

**Manual (when needed):**

```bash
python3 -m oto.harness.kernel_db --base-dir . --rebuild     # rescan gfx90c_runs/
python3 -m oto.harness.regression_matrix --base-dir .       # rebuild matrix from cache
```

`kernel_db` walks `gfx90c_runs/`: every `run_*` dir is native, every
`gfx900_ref_locked_*` dir is the spoof floor (`--all-ref` also folds the other
`gfx900_ref_*` rebuilds — excluded by default so regens stay identical to §12).
Per (phase, kernel-shape) it records the structural config (from the folder's
`Data/00_Final.yaml`; the floor's config is rebuilt from the solution name),
per-seed `gflops_best`, `gflops_median`, `n_seeds`, resolved dtype.

Regen determinism was verified: the repo's `kernel_db.json` is row-for-row
identical to the corpus snapshot that produced §12.

### 2. Read the signal

`regression_matrix` prints one row per shipped cell: deck median, floor
median, `% vs floor`, and per-cell verdicts:

* **losses** — deck median >2% under the floor median (config-identical
  flagged separately);
* **wins** — deck median >2% over the floor;
* **material median regressions** — a *non-deck* native kernel beats the deck
  by >2% on the same cell (the one place a candidate can still be *proven*
  better without a new run).

Current state: see [`docs/gfx90c_results.md`](../docs/gfx90c_results.md) for the live benchmark ledger and
published figures (wins/ties/losses and any material findings).

### 3. Resolve per-cell native-vs-floor winners (full knob surface)

`cell_resolver` turns "regression_matrix says CC:256 is a loss" into the exact
winning native phase / run / config and the floor kernel to beat — the input
the per-cell triage (docs/gfx90c_tuning_guide.md §13 §3/§5) and any spoof-steal
(§9: **configure, never copy**) are argued from:

```bash
python3 -m oto.harness.cell_resolver                      # table + caches (JSON, full.txt)
python3 -m oto.harness.cell_resolver --tsv verdicts.tsv   # + tabular verdict dump
```

For every acceptance-gradeable cell it reports: verdict, delta %, % of
realistic ceiling and % of theoretical peak; a **`cfg_gap`** class
(`identical` / `near` / `retile` / `no-floor`) between the native winner's config
and the floor's — the mechanical half of the tie taxonomy, whose reading is
docs/gfx90c_tuning_guide.md §13 §R17; the **native winner** — phase,
run, and the phase's full structural config, resolved winner-run-first from
the run dirs' `configs/*.yaml`, then registry `phases.data.config`, then the
kernel_db structural row; and the **floor's best kernel** for the same cell
(median-primary, best-seed secondary — the same `_best` predicate as
regression_matrix). It never measures anything; it reads acceptance_report.json
+ registry.db + kernel_db.json + the run config yamls only, and regenerates
`gfx90c_results/analysis/cells_resolved.json` / `.full.txt` (gitignored build
caches, like kernel_db.json) — deterministic re-runs of the §2 evidence table.

### 4. Propose a candidate — the gates that apply

1. **Coverage parity (the hard rule).** The produced `tensilelibrary.dat`
   must address exactly the shipped cells (no contraction, no extension). See
   [`docs/gfx90c_results.md`](../docs/gfx90c_results.md) §12 for the exact cell count and non-cube shapes.
   After any `phases.yaml` edit:
   ```bash
   python3 -m oto check library-parity --quiet && echo "grid-safe"
   python3 -m pytest -q tests/test_library_parity.py
   ```
   The suite is CPU-only and fast (2 m 10 s serial, 1 m 27 s with
   `pytest -n auto`, 37 s for `pytest -m preflight`): the YAML reader uses
   libyaml, the corpus reads are memoised and the legality gates are cached
   by config content. `OTO_GUARD_FILES=1` narrows the tree-walking guards
   (`test_function_length`, `test_pyflakes`, `test_ruff`, `test_py_compile`, `test_file_length`) to the files git reports as
   changed.
   Non-cube probe shapes have no cell: they are fine to measure, reported as
   non-cube shapes (never under coverage).
2. **Occupancy (CPU gate).** New kernels must pass
   `oto.tensile.gates.occupancy.occupancy_feasible`, which enforces three
   calibrated 0-false-rejection constraints: the per-thread accumulator cap
   (`TT0*TT1*R <= 128`), the workgroup register-file cap (`R*MT0*MT1*LSU <
   65536`, Tensile error 4), and the LSU LDS-reduction cap (`LSU*MT0*MT1*compute
   <= 65536`). Register-file wg/CU 512–8192. No occupancy regression below the
   floor's. Current gate status is reported by the live tools
   (`python3 -m oto.harness.gate_calibration --population ours`). **To add a
   rule, probe it first:** `python3 -m oto.harness.rule_calibration --rule
   <module:attr>` applies a `config -> Optional[bool]` predicate to the corpus
   and prints its false rejections (must be 0) and catches; the `builtin_rules`
   registry ships the shipped rules as views of the gate plus the rejected
   `nt_budget` counter-example. A candidate is also bounded by the classic
   global-load divisibility rule (`oto.tensile.gates.loads`): above 16384
   elements only 256×128 / 128×256 survive (plus 64×512 at DU8 for the
   16-bit-input families), and CC, DD and ZZ admit none at all —
   `docs/gfx90c_theoretical_limits.md` §5.1, pinned by
   `tests/test_tile_frontier.py`.
3. **Winner + tie rules.** Never compare best-of-runs to best-of-history; use
   median-of-seeds (`n_seeds >= 3`), tie band ±2% (the shipped-floor legacy
   band is 5%, documented separately). Never re-propose SS 96x96x8/6x6/VW2 or
   HH GlobalSplitU=2 (hard walls, §8).
4. **Preflight + consolidate gates** re-run the parity check automatically:
   `oto doctor` and `oto consolidate --commit` refuse a
   deck that breaks the grid.

### 5. Ask Tensile, not the model (the legality oracle)

> The three implementation modules behind this section -- `oto.yaml_cached` (the
> libyaml reader every YAML read goes through), `oto.tensile.contraction_patterns` (one
> spelling, one meaning for the contraction patterns) and
> `oto.tensile.gates.memo` (the content-keyed cache the gates use) -- are
> listed in `oto/README.md` and `docs/harness_runbook.md`.

The gates are **models** of Tensile. A model that says "legal" while Tensile
says "0 valid solutions" costs a launch slot and a wasted phase -- the
2026-10-20 run spent 8 phases on tiles that cannot be built. So every
legality question that the model cannot answer is settled by asking Tensile:

```bash
# one config: does Tensile build it, and what did it derive?
python3 -m oto.harness.tensile_probe --dtype S --macro 128x128x16 \
    --thread 8x8 --vw 4 --du 16 [--wgm -1] [--extra Knob=Value] [--pattern Alik_Bjlk]

# every UNMEASURED deck row (the pre-run sweep; ~75 s/row, resumable, CPU-only)
python3 -m oto.harness.deck_probe --family CC --limit 10
python3 -m oto.harness.deck_probe --json gfx90c_results/analysis/deck_probe.json
```

The oracle prints **both** verdicts side by side -- the launch gate's and
Tensile's -- plus the LDS allocation Tensile derived, so a disagreement says
which of the two is wrong. It is how the load-divisibility bug was found
(the gate modelled `totalVectorsCoalesced` as the coalesced part alone), and
how the `TransposeLDS=1` / `StaggerU=0` / `NonTemporalC` axes were found to
have been *declared but never emitted* (silent placebos).

**When you add a knob, prove it three ways:** it is in `FORWARDED_KNOBS`, the
fork surface test pins it (`tests/test_writer_forwards_sweep_knobs.py`), and
the oracle shows Tensile receiving it.

### 6. Know the space before you search it

```bash
python3 -m oto.harness.coverage_map --family SS --cell SS:256   # legal space + gaps
python3 -m oto.harness.coverage_graph                            # the pictures
```

The coverage map answers "what has NOT been measured" (87-93 % of the legal
geometry space, per cell) and the graph answers it as a picture: the legal
space is a band, the corpus has measured a thin strip through it, and the
traps (a legal configuration whose measured neighbours are all faster) sit
*inside* that strip. The R49 deck batch is that list, ranked.

### 7. Ship the legal tile frontier (§R40)

Authoritative green-lighted next step (user runs in a TTY): wire the seed
overlay (`python3 -m oto.harness.candidate_generator`; the overlay is
gitignored, so this is required), run the CPU-only preflight, then
`python3 -m oto tune --budget 10 --yes`. The deck rationale and its
four-outcome reading are in `docs/gfx90c_tuning_guide.md` §13 §R40. After the run, rebuild
the matrix (`step 1`) and re-check parity (`step 3`).

## Why medians, not best seeds

Best-seed comparisons are tail-prone — e.g. the D:192 all-time *best*
41.96 GFlops came from a kernel whose median is 17.67, and the HH:256 floor
"win" flips sign between bases (best-seed −31% vs median +2.5%). Median-first
is the standing rule everywhere in this repo (`changelog.md`;
`docs/gfx90c_tuning_guide.md` §13 §6 states the median-of-seeds basis).
## Visual/layout regression check (`oto.harness.visual_check`)

After regenerating `acceptance_report.html`, run the visual check to catch
layout regressions at desktop (1440px) and mobile (390px) viewports:

```bash
python3 -m oto.harness.visual_check gfx90c_runs/.../acceptance_report.html
# or served:
python3 -m http.server 8765 &
python3 -m oto.harness.visual_check gfx90c_runs/.../acceptance_report.html --url http://127.0.0.1:8765
```

Checks performed:
- No page-level horizontal overflow at either viewport
- Table wrappers correctly scroll (table wider than wrapper)
- Metric grid has 6 columns (desktop) / 2 columns (mobile)
- Key sections present: Family matrix, Problem-space coverage

Pinned by `tests/test_visual_check.py` (runs on the latest report artifact).

---

## CPU-only command card (folded from agent_reference.md)

## Quick Start

```bash
# 0. What has the corpus already measured here?
python3 -m oto.harness.corpus_census --cell SS:1024
python3 -m oto.harness.corpus_census --family SS --knob DepthU

# 1. Is the environment healthy?
python3 -m oto.tools.deck_review score
python3 -m oto.tools.deck_review legality
python3 -m oto.tools.deck_review flood --cap 24

# 2. CPU-only pre-flight
python3 -m oto check candidates --quiet
python3 -m oto.harness.candidate_generator --dry-run
python3 -m oto doctor

# 3. Pyflakes + ruff + py_compile + length safety nets (fast, CPU-only)
python3 -m pytest tests/test_pyflakes.py tests/test_ruff.py tests/test_py_compile.py tests/test_function_length.py tests/test_file_length.py -q
OTO_GUARD_FILES=1 python3 -m pytest tests/test_pyflakes.py tests/test_ruff.py tests/test_py_compile.py tests/test_function_length.py tests/test_file_length.py -q  # changed files only

# 4. Full test suite (2m10s serial, 1m27s with -n auto)
python3 -m pytest -q
python3 -m pytest -q -n auto          # distributed (pytest-xdist)
python3 -m pytest -q -m preflight      # the pre-run subset the checklist runs (37 s)

# 5. Gate calibration / failure triage (CPU-only, read-only)
python3 -m oto.harness.gate_calibration --population ours
python3 -m oto.harness.failure_triage
python3 -m oto.harness.rule_calibration               # probe proposed rules
```

## Key Files

| File | Purpose |
|---|---|
| `docs/potential_configs.md` | Deck methodology (device-independent); the gfx90c record is `docs/gfx90c_tuning_guide.md` §13 |
| `docs/gfx90c_tuning_guide.md` §1.1–§1.2, §9.1 | Primary-source knob reference + geometry |
| `docs/invariants.md` | Stage 0–3 search order + NOT VERIFIED note |
| (research corpus: deleted — durable facts promoted to this doc + docs/gfx90c_tuning_guide.md + docs/invariants.md) | absorbed |
| `oto/device/loader.py` | Device profile access — `resolve_profile(profile=None)` is the choke point for explicit gates/engines (`None` = ambient `current_profile()`), the canonical device view |
| `oto/device/kernel_vocabulary.py` | Cell/kernel vocabulary (cell_key, cube_side, shipped_cells, ...) |
| `oto/device/profile.py` | DeviceProfile dataclass (the frozen profile schema) |
| `oto/device/device_detect.py` | `detect_codename()` — auto-detect via rocminfo |
| `oto/yaml_cached.py` | The project's YAML reader: libyaml when present, memoised by content |
| `oto/tensile/gates/memo.py` | The content-keyed memo the pure legality gates use |
| `oto/tensile/family_decks.py` | FAMILY_DECKS, KNOB_SWEEPS, PLAN_BATCH |
| `oto/tensile/gates/occupancy.py` | LDS + VGPR occupancy gate |
| `oto/tensile/gates/loads.py` | Classic-path global-load divisibility + 16B cap |
| `oto/tensile/gates/assembly.py` | Assembly-class gate (MFMA rejection is here) |
| `oto/tools/deck_review.py` | The three pre-deck questions; its legality census draws the device-truth domain |
| `oto/harness/kernel_db.py` | kernel_db.json builder |
| `oto/harness/corpus_census.py` | Corpus history: axis/geometry coverage and per-cell geometry history, from kernel_db |
| `oto/harness/gate_calibration.py` | Gate-vs-corpus agreement census: false rejections (gate too strict) and misses (gate too loose) |
| `oto/harness/rule_calibration.py` | Probe a proposed gate rule in isolation: false rejections (must be 0) + empty-phase catches, by family |
| `oto/harness/failure_triage.py` | Empty-phase reason census: why a phase produced no measurement |
| `oto/harness/cell_resolver.py` | Per-cell native+floor winner resolver + the `cfg_gap` tie class |
| `oto/harness/coverage_map.py` | The legal geometry space per cell, what the corpus measured in it, and the unmeasured geometries ranked by their neighbours' score |
| `oto/harness/tensile_probe.py` | The legality oracle: Tensile's own verdict on a config, the LDS it allocated, and our gate's verdict beside it |
| `oto/harness/deck_probe.py` | The pre-run sweep: every *unmeasured* deck row through Tensile's kernel writer, resumable, CPU-only |
| `oto/harness/coverage_graph.py` | The coverage graphs: the legal geometry space per cell as a 2D picture, with the unexplored part hatched, the peaks ringed green and the traps ringed red |
| `oto/metrics/report_coverage.py` | The acceptance report's problem-space coverage section (the figures + their numbers) |
| `oto/tensile/contraction_patterns.py` | The contraction-pattern vocabulary: one spelling, one meaning (the transpose flags and the TLU layout flags) |
| `oto/harness/candidate_rows.py` | The candidate deck (`PLAN_BATCH`) and the emitted-overlay rows |
| `oto/tensile/config_writer.py` | The launch boundary: `FORWARDED_KNOBS` / `NOT_FORWARDED_KNOBS` |
| `tests/conftest.py` | The `serial` / `preflight` markers, the serial rule, the corpus fixtures |
| `tests/test_pyflakes.py` | Pyflakes safety-net guard |
| `tests/test_ruff.py` | Ruff safety-net guard (pinned rule set in `ruff.toml`) |
| `tests/test_py_compile.py` | Every tracked `.py` must byte-compile |
| `tests/test_file_length.py` | No tracked `.py` over 600 lines (grandfathered list ratchets down) |
| `tests/test_element_assertions.py` | AssertFree* dimension guard |
| `tests/test_tile_frontier.py` | The legal MacroTile frontier above 16384 elements |
| `tests/test_corpus_census.py` | Corpus-history census: median basis, geometry collapse, per-cell history |
| `tests/test_donor_mutator.py` | GlobalSplitU ban guard |
| `tests/test_deck_review.py` | Deck-review scores counter guard |
| `tests/test_function_length.py` | the 60-line function rule (tests/test_function_length.py) |

## Hardware — gfx90c (reads from `docs/gfx90c_tuning_guide.md` §0–§1.2)

- 7 CUs / 28 SIMDs / 448 FP32 lanes / Wave64 / 1800 MHz
- LDS 64 KiB/CU (2 WG budget at 32 KiB/WG)
- L2 1 MiB / DDR4 UMA ~42 GB/s → 38 F/B machine balance at SS peak
- **No MFMA** (ISA 9,0,12): MatrixInstruction rejected outright
- 16 B global-load cap (GLVW × bpe ≤ 16)
- Max VGPR 256/thread → accumulator budget is binding

## Pattern: what wins

1. **ThreadTile area scales inversely with bytes-per-element**: HH 8×8, SS 8×8 (111 VGPR),
   DD/CC 4×4, ZZ 2×2. Each sits at the largest TT satisfying `TT_area × bpe ≤ ~64`
   accumulator VGPRs.
2. **LDS at the winner is always 16–25 KB**, never 64 KB (2–4 resident workgroups).
3. **WGM is 4 or 8 at every winner**, never 1 (keeps neighbouring CUs on the same B slice).
4. **The floor never pads CC/DD/ZZ** — the highest-yield untested axis.
5. **The floor never uses** FractionalLoad=2, PGR=2, LdsPad, StaggerU. (It also
   never uses `WaveSeparateGlobalRead` / `1LDSBuffer` / `TransposeLDS` — but those
   are *unreachable*, not merely unmeasured: the launch boundary does not forward
   them, so a candidate naming one benchmarks at the default. See R16.)
6. **Empty on cc/zz**: no LdsPad; on then on for ss/hh — structural blind spot.
7. **MacroTile area above 16384 is legal only for 256×128 / 128×256** (VW2, or
   VW4 under `AssertFree1ElementMultiple`), plus 64×512 / 512×64 at DU8 for the
   16-bit-input families. CC, DD and ZZ admit **no** legal tile above 16384 at
   all, so their ORANGE cells are a bar artifact — `docs/gfx90c_theoretical_limits.md`
   §5.1, deck in `candidate_rows._FRONTIER`.

## Verdict bases (per `oto/metrics/ab_delta.py`)

| basis | meaning | interpretation |
|---|---|---|
| `winner` | native best-kernel vs spoof best-kernel | drop-in question |
| `median` | typical native vs typical spoof | median-of-seeds basis |
| `floor_best` | typical native vs spoof's BEST | **co-primary, cherry-pick-proof** |
| `strict` | native worst vs spoof best | literal "every way" dominance |

Report `floor_best` as co-primary alongside `winner`.

## Route status (from `docs/gfx90c_tuning_guide.md` §13 §8–§9)

| route | status | cells |
|---|---|---|
| A: spoof-steal (CC:256) | decked, 52 rows in PLAN_BATCH | CC:256 |
| B: 14 never-varied knobs | decked in KNOB_SWEEPS | all families |
| C: wave-quantisation ladder | legal only for SS/DD | SS, DD small shapes |
| D: LDS-capacity ladder for Z | decked (at-budget ladder; D2/D3 trials retired 2026-11-14) | ZZ all |
| E: split-complex (3 real GEMMs) | separate work item | CC, ZZ |
| F: persistent fixed grid | conceptual only | all |

## Reading the deck's stragglers

`python3 -m oto.harness.coverage_graph` draws the corpus's coverage of the
problem space: one SVG per contract cell (plus an index page) with the legal
geometry space projected onto (macro-tile area x accumulators per thread), the
measured part painted with the value it reached, the legal-but-unmeasured part
hatched, and the local maxima (peaks) and local minima (traps) ringed. The
headline it carries: **86-93 % of the legal geometry space has never been
measured** in every cell but ZZ, and the traps sit *inside* the measured strip
-- the search keeps falling back on a configuration whose neighbours are
3-8x faster.

`python3 -m oto.harness.tensile_probe --dtype Z --macro 64x64x8 --thread 2x2
--vw 1 --du 8` asks **Tensile itself** whether a config builds, what LDS it
allocated and what our gate said -- the way to settle a legality question the
CPU gates cannot answer (it is what found the load-divisibility bug: the gate
modelled `totalVectorsCoalesced` as the coalesced part alone, so its NLCA check
was against the wrong number).

`python3 -m oto.harness.coverage_map --cell SS:256` answers the question the
census cannot: not "what has been measured" but "what *could* have been" -- the
legal geometry space per cell, the part of it the corpus covers (8-13 %), and
the legal-but-unmeasured geometries ranked by how well their neighbours
measured. That is the local-minimum finder: the neighbourhood is fast and the
point itself is untried.

`python3 -m oto.harness.cell_resolver --taxonomy` says what each verdict is
made of: on the `identical` cells both arms run the *same* config, so their
delta is measurement environment, and the spread over those cells (17.5
points) is the band any real win has to clear.

`python3 -m oto.harness.cell_resolver` prints one row per cell with a `cfg_gap`
class; `docs/gfx90c_tuning_guide.md` §13 §R17 reads it into a route:

| `cfg_gap` | meaning | lever |
|---|---|---|
| `identical` | native ties on the floor's own tile | co-vary a *forwarded* knob at that tile |
| `near` | same tile, a VectorWidth/DepthU step apart | the width/depth step |
| `retile` | native ties on a *different*, smaller tile | a tile probe, not a width probe |
| `no-floor` | the family ships no floor arm (HPA) | nothing — native is already above the ceiling |

Before proposing the probe, read the cell's full history:
`python3 -m oto.harness.corpus_census --cell FAM:side` lists every geometry the
corpus has measured on that cell, the row count behind each, and the floor's
best — so a `retile` route cannot re-propose a geometry that already lost, and
`docs/gfx90c_tuning_guide.md` §13 §R41's closed axes stay closed.

## Do not search

- `MatrixInstruction` / `DirectToLds` — rejected or actively harmful
- `ThreadTile` width ladders for C/Z — the per-thread accumulator cap (`TT0*TT1*R
  > 128`) makes every wider thread tile illegal
- **Wider MacroTile for C/Z** — provably closed (`docs/gfx90c_tuning_guide.md` §13 §R27):
  the workgroup register-file rule (`R*MT0*MT1*LSU < 65536`) caps area at
  `65536/R`, so the widest legal complex tiles are CC `128x64` and ZZ
  `64x64`/`128x32`; a brute force above those areas finds none legal
- `LdsPad`/LDS-layout work on bandwidth-oversupplied families
- `-mllvm -amdgpu-*` compiler flags (no-op: ~93% of shipped library is ISA text)
- `AggressivePerfMode=2` — now **refused at the generator seam**
  (`candidate._non_generative_knob_rejection`): the assembly path cannot emit it
  (`Components/Priority.py` dispatches only 0/1, so `MAC_F32C` raises
  `TypeError`). 0/28 built across every family. The writer still forwards it by
  contract. See `docs/gfx90c_tuning_guide.md` §13 §R24.
- `MaxOccupancy` assumptions without measurement
- `WaveSeparateGlobalReadA/B`, `ThreadSeparateGlobalReadA/B`, `1LDSBuffer`,
  `TransposeLDS`, `UnrollMajorLDSA/B`, `LdsBlockSizePerPadA/B`, `DirectToVgprA/B`
  — **not forwarded** by the launch boundary (`config_writer.NOT_FORWARDED_KNOBS`),
  so decking one benchmarks at the default until R20 funds both the forwarding and
  its gate. The harness now strips and *reports* these instead of no-op'ing silently.

## CPU-only contract (`claude.md` §5)

- **Never stress the GPU** from a GNOME session (no sustained `./benchmark` runs)
- `oto check candidates`, `python3 -m oto.harness.candidate_generator --dry-run`, and `oto doctor` are safe
- Real benchmarking happens in the user's TTY only
- CPU-only legality proofs: `validate_config`, `ldspad_feasible`, `occupancy_feasible`
- **Any `pytest` invocation during programming takes minutes and must be run in
  the background** (background mode) so the conversation is not blocked; read the
  result when it completes. Never sleep/poll for it.
- **The suite is fast now** (2 m 10 s serial, 1 m 27 s with `-n auto`,
  37 s for `-m preflight`): the YAML reader uses libyaml, the corpus reads are
  memoised and the legality gates are cached by config content. A run that
  takes longer than that is doing something new -- check the durations
  (`pytest --durations=10`) before assuming the machine is slow.

## The overnight run command

```bash
# CPU-only (any session)
python3 -m oto.harness.candidate_generator          # wire the seed overlay
python3 -m oto check candidates --quiet
python3 -m oto check candidates --deck gfx90c_results/overlays/phases.seed.overlay.yaml --quiet
python3 -m oto.harness.candidate_generator --dry-run
python3 -m oto doctor

# TTY only — the real run
python3 -m oto tune --budget 10 --yes
```

The overlay is gitignored, so wiring it in is a required step, not a no-op.
The run's phase count is the committed deck plus the overlay rows; read the
overlay count and the dry-run's "would append N" line (0 after a correct wire)
rather than trusting a literal pinned here (`claude.md`: "Never write a corpus
count down — anywhere"). `--budget 10` makes the run exit once the deck is
exhausted.
Judge **within-run only**, ≥3 seeds, median, ±2% tie band.

## Post-run read guide

```bash
python3 -m oto.harness.kernel_db --rebuild
python3 -m oto.harness.cell_resolver            # per-cell winners + cfg_gap
python3 -m oto stats --json > gfx90c_results/analysis/post.json
python3 -m oto.runners.stage_cli --report --native-agg floor_best   # the strict basis
```

Report `floor_best` as co-primary alongside `winner`. Look for `LdsPad` win on
CC/ZZ/DD (bank-conflict lever) and `FractionalLoad=2` on ragged shapes.
## Report regeneration & visual check

After a run completes and the JSON payload is written, regenerate the HTML
dashboard and run the visual check:

```bash
# From repo root; regenerates acceptance_report.html in the run dir
python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, '.')
from oto.metrics.report_models import ABVerdict, AcceptanceReport
from oto.metrics.acceptance_report import AcceptanceReporter
run = Path('gfx90c_runs/run_...')  # the run ID
payload = json.loads((run / 'acceptance_report.json').read_text())
payload['per_cell_verdicts'] = [ABVerdict(**v) for v in payload.get('per_cell_verdicts', [])]
report = AcceptanceReport(**payload)
AcceptanceReporter(Path('.').resolve()).write_html_report(report, run / 'acceptance_report.html')
PY

# Visual/layout regression check (requires playwright + chromium)
python3 -m oto.harness.visual_check gfx90c_runs/run_.../acceptance_report.html
```

The visual check validates no horizontal overflow, correct table scrolling,
metric grid column counts, and section presence at desktop (1440px) and mobile
(390px) viewports.
