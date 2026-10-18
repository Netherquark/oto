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
oto/harness/regression_matrix.py  # regression_matrix.json builder (deck vs floor vs all-time)
oto/harness/resolve_cells.py      # per-cell winner resolver + cfg_gap (full knob surface)
oto/tools/deck_review.py          # the three pre-deck questions (score/legality/flood)
docs/harness_runbook.md            # this runbook
gfx90c_results/analysis/kernel_db.json          # cache (rebuilt)
gfx90c_results/analysis/regression_matrix.json  # cache (median basis, per-family grid)
gfx90c_results/analysis/cells_resolved.json     # cache (winner map; resolve_cells)
gfx90c_results/analysis/cells_resolved.full.txt # same, human table (potential_configs.md §3)
```

Module list and ownership: see [`oto/README.md`](../oto/README.md) for the harness
modules (e.g. `oto/harness/*`). Both tools resolve families/shapes/dtype from the
repo's canonical sources (`oto.device.peaks`, `oto.tensile.library_parity`) — they
can never disagree with the shipped grid (knowledge_base.md §6.1). Cache paths are
listed above.

## The three questions, before you deck anything

`oto/tools/deck_review` is the pre-flight for candidate generation. It answers
the three questions in order, all CPU-only and read-only:

```bash
python3 -m oto.tools.deck_review score            # is the floor actually beaten?
python3 -m oto.tools.deck_review legality         # is this knob domain deck-safe?
python3 -m oto.tools.deck_review flood --cap 24   # where is the GPU budget going?
```

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
`db_knobs.py`; `python3 check_candidates.py` on the real deck — which sees every
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

Current state: see [`results.md`](../results.md) for the live benchmark ledger and
published figures (wins/ties/losses and any material findings).

### 3. Resolve per-cell native-vs-floor winners (full knob surface)

`resolve_cells` turns "regression_matrix says CC:256 is a loss" into the exact
winning native phase / run / config and the floor kernel to beat — the input
the per-cell triage (potential_configs.md §3/§5) and any spoof-steal
(§9: **configure, never copy**) are argued from:

```bash
python3 -m oto.harness.resolve_cells                      # table + caches (JSON, full.txt)
python3 -m oto.harness.resolve_cells --tsv verdicts.tsv   # + tabular verdict dump
```

For every acceptance-gradeable cell it reports: verdict, delta %, % of
realistic ceiling and % of theoretical peak; a **`cfg_gap`** class
(`identical` / `near` / `retile` / `no-floor`) between the native winner's config
and the floor's — the mechanical half of the tie taxonomy, whose reading is
potential_configs.md §R17; the **native winner** — phase,
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
   [`results.md`](../results.md) §12 for the exact cell count and non-cube shapes.
   After any `phases.yaml` edit:
   ```bash
   python3 check_library_parity.py --quiet && echo "grid-safe"
   python3 -m pytest -q tests/test_library_parity.py
   ```
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
   `nt_budget` counter-example.
3. **Winner + tie rules.** Never compare best-of-runs to best-of-history; use
   median-of-seeds (`n_seeds >= 3`), tie band ±2% (the shipped-floor legacy
   band is 5%, documented separately). Never re-propose SS 96x96x8/6x6/VW2 or
   HH GlobalSplitU=2 (hard walls, §8).
4. **Preflight + consolidate gates** re-run the parity check automatically:
   `port_tensile.py --preflight` and `consolidate.py all --commit` refuse a
   deck that breaks the grid.

### 5. Ship the S:512 / HH_HPA:4096 probes

Authoritative green-lighted next step (user runs in a TTY):
`python3 port_tensile.py --auto --yes --budget 10 --mutation-budget 2 --live off`
with seed overlay = N1–N5 + **N6** (SS:512 vw4 floor kernel) + **N7**
(the HH_HPA:4096 stranded winner carried as a deck D-row). After the run,
rebuild the matrix (`step 1`) and re-check parity (`step 3`).

## Why medians, not best seeds

Best-seed comparisons are tail-prone — e.g. the D:192 all-time *best*
41.96 GFlops came from a kernel whose median is 17.67, and the HH:256 floor
"win" flips sign between bases (best-seed −31% vs median +2.5%). Median-first
is the standing rule everywhere in this repo (`changelog.md`;
`potential_configs.md` §6 states the median-of-seeds basis).