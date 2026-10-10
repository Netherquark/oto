# harness — agentic kernel-tuning harness (CPU-only)

Polished, repo-homed home of the candidate-generation machinery that was built
ad-hoc in `/tmp` (now deleted as a source of truth). The read-only tools plus
this runbook give an agent (or a human) the ground truth needed to propose a
defensible candidate without re-reading the raw corpora. Nothing here ever
benchmarks or touches a GPU — the measurement corpus is fixed until a TTY run
lands (see `command.txt`).

## Layout

```
harness/kernel_db.py          # kernel_db.json builder (ground truth)
harness/regression_matrix.py  # regression_matrix.json builder (deck vs floor vs all-time)
harness/resolve_cells.py      # per-cell native+floor winner resolver (full knob surface)
harness/README.md             # this runbook
gfx90c_results/analysis/kernel_db.json          # cache (rebuilt, byte-identical to §12)
gfx90c_results/analysis/regression_matrix.json  # cache (median basis, per-family grid)
gfx90c_results/analysis/cells_resolved.json     # cache (38-cell winner map; resolve_cells)
gfx90c_results/analysis/cells_resolved.full.txt # same, human table (potential_configs.md §2)
```

Both tools resolve families/shapes/dtype from the repo's canonical sources
(`gfx90c_common`, `library_parity`) — they can never disagree with the shipped
grid (knowledge_base.md §6.1).

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
python3 -m harness.kernel_db --base-dir . --rebuild     # rescan gfx90c_runs/
python3 -m harness.regression_matrix --base-dir .       # rebuild matrix from cache
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

Published state (2026-10-07): **16 wins / 13 ties / 9 losses**, 8 loss cells
config-identical (cross-run variance, re-measure only), **S:512 the only real
config difference** (deck VW2 771.9 vs floor VW4 801.6 → probe N6), and **one
material finding**: HH_HPA:4096's stranded iteration-9 winner
`phase_auto_1_hh_hpa_2048x2048x2048_4` (−4.0% at the median) should be shipped
as a D-row (probe N7).

### 3. Resolve per-cell native-vs-floor winners (full knob surface)

`resolve_cells` turns "regression_matrix says CC:256 is a loss" into the exact
winning native phase / run / config and the floor kernel to beat — the input
the per-cell triage (potential_configs.md §2/§4) and any spoof-steal
(§7: **configure, never copy**) are argued from:

```bash
python3 harness/resolve_cells.py                      # table + caches (JSON, full.txt)
python3 harness/resolve_cells.py --tsv verdicts.tsv   # + tabular verdict dump
```

For every acceptance-gradeable cell it reports: verdict, delta %, % of
realistic ceiling and % of theoretical peak; the **native winner** — phase,
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
   must address exactly the 38 shipped cells (no contraction, no extension).
   After any `phases.yaml` edit:
   ```bash
   python3 check_library_parity.py --quiet && echo "grid-safe"
   python3 -m pytest -q tests/test_library_parity.py
   ```
   Non-cube probe shapes (`32x4096x1`, …) have no cell: they are fine to
   measure, report them under §12's `non_cube_shapes`, never under coverage.
2. **Occupancy (CPU gate).** New kernels must pass
   `scheduler.occupancy_feasible` (45/45 rows pass today; register-file
   wg/CU 512–8192). No occupancy regression below the floor's.
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

§8.3: best-seed comparisons are tail-prone — e.g. the D:192 all-time *best*
41.96 GFlops came from a kernel whose median is 17.67, and the HH:256 floor
"win" flips sign between bases (best-seed −31% vs median +2.5%). Median-first
is the standing rule everywhere in this repo (changelog.md, potential_configs.md §12).