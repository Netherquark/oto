# harness — agentic kernel-tuning harness (CPU-only)

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
oto/metrics/report_figures.py        # the report's problem-space coverage section (reads the figures' hand-off)
oto/tools/deck_review.py          # the three pre-deck questions (score/legality/flood)
docs/harness_runbook.md            # this runbook
gfx90c_results/analysis/kernel_db.json          # cache (rebuilt)
gfx90c_results/analysis/regression_matrix.json  # cache (median basis, per-family grid)
gfx90c_results/analysis/cells_resolved.json     # cache (winner map; resolve_cells)
gfx90c_results/analysis/cells_resolved.full.txt # same, human table (docs/potential_configs.md §3)
gfx90c_results/analysis/coverage_map.json      # cache (legal space + coverage; coverage_map)
```

Module list and ownership: see [`oto/README.md`](../oto/README.md) for the harness
modules (e.g. `oto/harness/*`). Both tools resolve families/shapes/dtype from the
repo's canonical sources (`oto.device.loader`, `oto.tensile.library_parity`) — they
can never disagree with the shipped grid (docs/knowledge_base.md §6.1). Cache paths are
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
`docs/potential_configs.md` §R41 (the axes the corpus has finished with); the
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

Current state: see [`docs/results.md`](../docs/results.md) for the live benchmark ledger and
published figures (wins/ties/losses and any material findings).

### 3. Resolve per-cell native-vs-floor winners (full knob surface)

`resolve_cells` turns "regression_matrix says CC:256 is a loss" into the exact
winning native phase / run / config and the floor kernel to beat — the input
the per-cell triage (docs/potential_configs.md §3/§5) and any spoof-steal
(§9: **configure, never copy**) are argued from:

```bash
python3 -m oto.harness.cell_resolver                      # table + caches (JSON, full.txt)
python3 -m oto.harness.cell_resolver --tsv verdicts.tsv   # + tabular verdict dump
```

For every acceptance-gradeable cell it reports: verdict, delta %, % of
realistic ceiling and % of theoretical peak; a **`cfg_gap`** class
(`identical` / `near` / `retile` / `no-floor`) between the native winner's config
and the floor's — the mechanical half of the tie taxonomy, whose reading is
docs/potential_configs.md §R17; the **native winner** — phase,
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
   [`docs/results.md`](../docs/results.md) §12 for the exact cell count and non-cube shapes.
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
> listed in `oto/README.md` and `docs/agent_reference.md`.

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
four-outcome reading are in `docs/potential_configs.md` §R40. After the run, rebuild
the matrix (`step 1`) and re-check parity (`step 3`).

## Why medians, not best seeds

Best-seed comparisons are tail-prone — e.g. the D:192 all-time *best*
41.96 GFlops came from a kernel whose median is 17.67, and the HH:256 floor
"win" flips sign between bases (best-seed −31% vs median +2.5%). Median-first
is the standing rule everywhere in this repo (`changelog.md`;
`docs/potential_configs.md` §6 states the median-of-seeds basis).
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
