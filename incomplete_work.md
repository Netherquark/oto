# Incomplete Work register (re-verified 2026-09-13; refreshed 2026-09-26)

Status key: RESOLVED (mechanism landed + proven) / PENDING (real gap, still open) /
PARTIAL (mechanism landed; execution/validation outstanding).

## 4.14 In-Place Phases Fix & Telemetry v2 (RESOLVED — 2026-09-14)
- Fixed 48 invalid contraction entries in `phases.yaml` in-place (NLCA 3→1 ×46, DepthU 4→16 ×2; backup `archive/phases_20260914_prefix.yaml`).
- Replaced fragile telemetry sampler with `telemetry.py` (non-root sysfs, `mclk_hz` parsed correctly).
- Client/bench split PoC verified via `--prebuilt-client`.

**Gap (2026-09-26: CLOSED, now §4.15):** the frozen same-run pair (run_171325 =
0/11/0 parity) is superseded by the dedicated `gfx900_ref_*` reference floor;
verdicts are re-derived per workload cell vs the recalled floor chain
(ruler-adjusted, median-of-seeds, ±5% tie = parity).

## 4.15 Reference floor + per-cell A/B (RESOLVED — 2026-09-26; completion pending)

**Mechanism:** `tensile_library.py` parses the system ROCm gfx900 `TensileLibrary_*_gfx900.dat`
and pins 2,285 shipped kernels once at `gfx90c_results/gfx900_shipped_manifest.json`; every
report recalls the whole `gfx900_ref_*` chain (base + `--resume` continuations) via
`reference_chain` + `_compute_ab_verdicts`. `analytics.compute_native_vs_spoof_delta`
pairs by workload cell `(family, dtype, shape)` (`cell_key`) — best-of-cell median per
arm. The ±5% tie band originally used here is narrower than the corpus-measured
repeat noise (CV p90 27.8%, `ab_audit.repeat_dispersion`), so "parity" at ±5% does
not mean statistically indistinguishable; see `results.md` §12.3.

**the floor is 2,285 kernels, not 1,212.**
`gfx900_ref_20260925_152942` targeted 2,285 and was interrupted after 1,189
(1,073 completed / 116 failed); `gfx900_ref_20260926_201843_resume` targeted 1,212
of those and attempted every one. So the two runs between them attempted all
2,285. Any triage scoped to the resume deck alone would silently drop the 1,073
kernels the base run had already measured — every `tier_for` lookup is therefore
keyed by `tlib.phase_key()` (hash of the shipped solution name), and the resume
rebuild intersects against the manifest key set, not the loaded deck.
`phase_id` is *not* safe as an identity: 328 of 2,285 phase_ids change when the
deck is rebuilt after the config fixes, so pid-based triaging is unusable.

**Status:** the two runs now span the whole 2,285-kernel universe. Re-measurement
need is triaged in §4.16, and `--auto` gates tuning behind **T1 only**
(`_reference_remaining() == 0`).

**Residue/evidence:** `gfx90c_results/registry.db` 3,369 measured rows stamped
`cell_key`/`arm`/`kernel_key`; `idx_cell_key` index exists in the live registry
only — `registry.py` does not create it, so a fresh DB would miss it.

## 4.16 gfx900 floor triage: T1 active, T2 HELD (PARTIAL — T1 active, T2 pinned 2026-09-28)

**The problem.** Two independent defect classes made the shipped-kernel reference
floor untrustworthy. Both were ours, in the config *extraction*, not in Tensile:

1. **Incorrect config (127 kernels).** Our extractors mis-parsed the system
   `TensileLibrary_*_gfx900.dat`: the `VW` match was unanchored (so `VW1` leaked
   into `VectorWidth`), `TT4_2` was mis-parsed, and `GLVWA`/`GLVWB`/`GRVW` were
   never parsed at all. These phases ran with the *wrong shape*, so their
   numbers describe a computation we do not care about. Fixed in
   `tensile_library.py` (anchored `VW`, corrected `TT4_2`, full GLVW emission).
2. **Under-specified config (1,881 kernels).** `glvw`/`grvw` were left to
   Tensile's defaults rather than taken from the shipped solution name. The
   kernels are *correct*, just not pinned to what the vendor shipped, so the
   measurement is reproducible but not faithful to the intent. Also fixed in the
   parser — the rebuilt configs now pin all three values for all 2,285.

**Triage (`gfx90c_results/reference_rerun_manifest.json`, keyed by `phase_key`):**

| tier | n | behaviour | status |
|---|---|---|---|
| `T1_RERUN` | 127 | staged **first**, mandatory; `--auto` blocks until done | **ACTIVE** |
| `T2_RERUN_HELD` | 1,881 | not staged, does not block; opt-in only | **PENDING** |
| `T3_UNREPRODUCIBLE` | 277 | never staged, left failed | terminal |
| `T0_KEEP` | 0 | reuse the existing measurement | — |

127 + 1,881 + 277 = 2,285. T1's 127 = 64 Tensile rejections under the broken
config (rc=255, config-fixable) + 63 operator skips (rc=-1) that were therefore
never actually measured.

**T3 breakdown (277, terminal).** 154 half-input kernels pinned to `VW1` by
Tensile, 121 rejected by `assembly_class_valid()` (a real legality gap vs the
shipped `.dat`), 2 with no resolvable schedule. The vendored Tensile cannot
reproduce these; changing dtype or config to force them through would benchmark
a *different* computation, which is worse than a documented gap. Left failed.

**What is deliberately NOT in use (the pin).** T2's mechanism is fully landed
and tested — the shipped-config rebuild, the content fingerprint, the triaged
ordering, the hold/release switch — but the **staging decision is withheld**.
1,881 phases is ~1 day of GPU time to re-measure kernels that were never wrong,
for no correctness gain. The floor therefore keeps their existing
default-resolved measurements, and that is recorded rather than hidden.

Release when the floor is stable and a GLVW-faithful re-measurement is actually
wanted:

```bash
python port_tensile.py --gfx900-reference --release-under-specified
# or, via --auto:  python port_tensile.py --auto --release-under-specified
```

**Files:** `tensile_library.py` (`TIER_HELD`, `PINNED_TIERS`,
`apply_rerun_tiers(..., release_held=)`); `port_tensile.py`
(`run_gfx900_reference(..., release_held=)`, `run_auto(..., release_held=)`,
`--release-under-specified`); lists in `gfx90c_results/`:
`reference_rerun_first.txt` (127), `reference_rerun_last.txt` (1,881 held),
`reference_rerun_never.txt` (277); audit in
`reference_integrity_audit.json`.

**Verified (CPU-only, no GPU):** default deck stages **127** and nothing else;
`--release-under-specified` stages **2,008** with T1 first and T2 at the very
back; the `--auto` gate returns 127 owed → 0 once T1 completes, stays 0 with T2
untouched/partial/absent, and returns 27 with T1 at 100/127 — so held T2 can
never deadlock or falsely satisfy the floor. The real `--resume` path was
exercised with execution stubbed and reported `127 to run, 277 dropped, 1881
pinned as held`.

**To close:** run the 127 in a TTY, confirm the floor completes, then decide
whether T2 is worth its day. No code work is outstanding.

**2026-10-09 update — measurement-hygiene items that touch this tier land done:**
- kernel_db rebuilt with all runs folded (`harness/kernel_db.py --rebuild`): the
  locked-floor run contributes 14 019 kernel-shape rows; 19608 rows total.
- **Zero-contamination verified** on the rebuilt DB: 0 rows where the stored
  family disagrees with the kernel typecode (SB/DB/HB/CB/ZB → SS/DD/HH/CC/ZZ;
  HHS/HSS → HH); the `phase_auto_1_hh_*` rows that used to win SS:1024 at
  2142.55 are gone — honest SS:1024 is 1135.1. Root cause pinned and fixed in
  `analytics.py` (the `'auto'` FAMILY_TO_DTYPE entry) + `gfx90c_common.py`
  typecode resolvers (single source of truth), 28 unit tests
  (`tests/test_cell_attribution.py`).
- **Floor winner gate-legality proven** (`check_candidates.py --floor`): all 30
  per-cell floor winners pass all 4 legality gates natively; the 21 % whole-deck
  residue is generator-rule artifacts on non-winners plus 72 genuine
  occupancy-LDS entries (64-KB-LDS gfx900 kernels the APU's 16-KB-WG budget
  rejects — none ever won a cell).
- Real VGPR counts measured corpus-wide (`harness/measure_vgprs.py`) and the
  occupancy model's calibration is now measurement-ratified
  (`scheduler.MEASURED_VGPR_BY_DTYPE`).
- Full story: `gfx90c_tuning_guide.md`.


**Mechanism:** `port_tensile.py` + `phases.yaml` manifest + 7 modules (`registry.py`, `report.py`, `analytics.py`, `policy.py`, `scheduler.py`, `agent.py`, `gfx90c_common.py`) fully implemented and unit-tested. `--auto` convergence loop operational with deterministic mutate-≤2-knobs candidate generation.

## 4.3 28-family native coverage (RESOLVED — 2026-09-13)

**Mechanism (T3):** 28-family native coverage generated in `phases.yaml` spanning all 7 families `{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}` across 4   contraction patterns `{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}` with anchor problem shapes (304 candidate configs: 232 family + 72 auto; re-derived to **418 phases** 2026-09-27: 410 + 8 gate-legal ZZ replacements, see `changelog.md`.)

## 4.4 Adaptive-repeat finalize (RESOLVED — 2026-09-13)

**Mechanism:** Production adaptive repeat logic implemented in `port_tensile.py` (NumBenchmarks doubling for high-spread cells). Telemetry sampler in `telemetry.py` (`SysfsTelemetrySampler`) guarantees gated sample windows. *(2026-09-25: the `policy.py` `should_repeat`/`classify_stability` helpers were removed — stability is now a CV≤15% gate inside `agent.converged()`.)*

## 4.5 auto-retire trust gate (RESOLVED — 2026-09-13)

**Mechanism:** Implemented in `policy.py` (`check_retirement_eligibility`), gated on ≥2 independent runs/cell before emitting retirement decisions. *(2026-09-25: `classify_retirement_tier` and `apply_d2_4_protection` were removed — retirement is now the single Tier-2 path via `check_retirement_eligibility` + `should_run`/`is_config_retired`.)*

## 4.6 Peak-table prose drift (RESOLVED — 2026-09-13)

**Mechanism (T8):** Sourced strictly from `gfx90c_common.PEAK_GFLOPS` (single import point — BF16: 1613, INT8: 1613). All driver headers, analytics, and reports cite single-rate 1613.

## 4.7 Synthesis evidence gate (RESOLVED — 2026-09-13)

**Mechanism:** Implemented in `port_tensile.py` `synthesize_library()`. Emits per-family logic YAMLs, executes `TensileCreateLibrary --merge-files`, runs anti-alias scan rejecting any `gfx900`/`vega10` leaks, and verifies regression against 28 families.

## 4.8 Occupancy = performance objective (RESOLVED — 2026-09-13)

**Mechanism (T9):** `scheduler.py` candidate generator and `agent.py` convergence engine treat right-sized `GSU`/`WGM`/`MT`/`TT` as first-class objective knobs, scored against realistic ceilings in `gfx90c_theoretical_limits.md` §5.

## 4.9 Driver Implementation & Remediation (RESOLVED — 2026-09-13)

**Remediation audit completed and verified across all modules:**
- `port_tensile.py`: Added telemetry sampling (via `telemetry.py` `SysfsTelemetrySampler`, canonical units Hz/µW/mC/% logging to `logs/telemetry.csv`), interactive non-blocking `'s'` skip and `'q'` quit key listeners, fixed subprocess buffer deadlocks by piping to disk logs, fixed `run_ab_test` to query native (`ScheduleName="isa"`) and spoof (`ScheduleName="vega10"`) records separately, and implemented Stage 6 library synthesis with YAML logic generation, anti-alias scanning (`0` gfx900/vega10 leaks), and 2,285-kernel regression check (the earlier 3,066 was per-file token counting).
- `scheduler.py`: Fixed LDS usage calculation to `(M*K + N*K) * elem_size * NLCA / 1024.0`; fixed `parse_tensile_shape` to robustly handle batched (`_B16`) and explicit K (`_K4096`) shapes; improved wave-based occupancy estimation.
- `agent.py`: Upgraded `converged()` to evaluate full multi-condition convergence (≥2 independent runs, ≥3 distinct configs, ≤1% movement, and no RED cells); replaced hardcoded static fallback in `_reconstruct_config` with family-aware defaults.
- `registry.py`: Protected `append_phase` with `INSERT OR IGNORE` and duplicate checking.
- `policy.py` & `analytics.py`: Clean stdlib implementations using realistic ceilings from `gfx90c_theoretical_limits.md` §5.

## 4.10 Ctrl+C signal handler + stale-run cleanup (RESOLVED — 2026-09-13)

**Mechanism:**
- `_signal_handler` now calls `sys.exit(130)` after `os.killpg` + registry `update_run_status(interrupted)`.
- `registry.cleanup_stale_runs()` added (bulk UPDATE `started→interrupted`) and called in `TensileDriver.__init__` before creating new run dir.
- `run_phases()` marks run `interrupted` when `_stop_requested` is set.
- 3 orphaned runs (run_140507, run_141220, run_143006) corrected in live DB.

## 4.11 Tensile Top-Level YAML Generator & Pipeline Robustness (RESOLVED — 2026-09-13)

**Mechanism:**
- `port_tensile.py`: Fixed `_write_phase_config` to derive correct `TransposeA`/`TransposeB` per contraction pattern in label (`Ailk_Bljk` $\to$ NN/FF, `Ailk_Bjlk` $\to$ NT/FT, `Alik_Bljk` $\to$ TN/TF, `Alik_Bjlk` $\to$ TT/TT); mapped `MacroTile0`/`MacroTile1` properly from string representation; dynamically calculated `WorkGroup` tile ratios (`MacroTile0/ThreadTile0`, `MacroTile1/ThreadTile1`, 1); set proper HPA / `HS_HPA` mixed precision flags.
- `scheduler.py`: Added `MacroTile` / `ThreadTile` divisibility check (`MacroTile0 % ThreadTile0 == 0`) and valid thread count constraints ($64 \le \text{threads} \le 1024$, multiple of 64) in `validate_config`.
- `analytics.py`: Added whitespace-stripped parsing and per-kernel GFlops extraction in `load_benchmark_csv` to handle space-padded CSV headers emitted by Tensile.
- Verified across unit tests and live benchmark data (`run_20260913_144805`, `run_20260913_150517`, `run_20260913_151227`).

## 4.12 Complete 7-Stage Driver Transition (RESOLVED — 2026-09-13)

**Mechanism:**
- Abolished reliance on arbitrary numeric phase IDs (0–31); phase identity uses
  semantic filters.
- Replaced CLI execution with semantic filters: `--family` (SS, HH, HH_HPA, HS_HPA, DD, ZZ, CC), `--pattern` (Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk), `--shape`, `--stage`, and `--auto`.
- `phases.yaml` fully populated with 28 native families across 4 contraction patterns (228 clean targets; the live manifest = **418 phases** as of 2026-09-27, see `results.md` §1).
- Added `--dry-run` to inspect matched candidate targets before hardware execution.

## 4.13 Parallel Clang Build, Cooldown Key Handling & Early Quit Reports (RESOLVED — 2026-09-13)

**Mechanism:**
- Multi-threaded assembly compilation enabled by setting `CpuThreads: min(os.cpu_count(), 16)` in generated YAMLs and `make -j`.
- Fixed Tensile `ForkParameters` emission from `MacroTile0`/`MacroTile1` to valid schema `MacroTile: [[M0, M1, DepthU]]` fixing CC/DD configuration parsing.
- Integrated non-blocking `select.select()` listener in `_apply_cooldown()` so `'s'` skips cooldown sleep and `'q'` quits immediately.
- Ensured `acceptance_report.json` and `acceptance_report.html` are generated and persisted to `gfx90c_results/` even on early termination via `'q'` or interruption.## 5.1 Refactor 1 (codebase organisation) — PARTIAL (2026-10-11)

Shipped: the flat root moved into an `oto/` package by responsibility, the three
gate families extracted from `scheduler.py` into `oto/tensile/gates/`, the
god-module (`port_tensile.py`, 3626 lines) split into
`oto/runners/{driver,benchmark,phases,reference,auto,reporting,analytics_loaders,
clocks,timing,synthesis,cli,toolchain,flags}` plus `oto/tensile/config_writer.py`,
and the remaining oversized modules split per
`plans/REFACTOR_1_CODEBASE_ORG.md` section 3.

No behaviour change. Proven five ways against the pre-refactor commit
(`python3 plans/verify_all.py`):

* `verify_gate_differential.py` — 128,032 comparisons of every scheduler
  gate/function over an exhaustive config corpus, all equal.
* `verify_method_equivalence.py` — all 57 TensileDriver methods that moved into
  a mixin have an identical AST body.
* `verify_config_writer.py` — 6,037 live phases, old vs new config writer agree on
  (ok, reason) AND on the exact YAML bytes: 5,693 written, 344 refused, 0
  mismatches.
* `verify_report_html.py` — the rendered acceptance dashboard is byte-identical
  (99,287 bytes). This is the proof that the A/B delta arithmetic is unchanged.
* `verify_ast_equivalence.py` — every public symbol of every pre-split module
  still exists with the same body; 0 unexplained differences.

### PENDING — functions still over 60 lines (51 of them, 5,237 lines total)

Acceptance criterion 2 of the plan ("no function over 60 lines") is **not yet
met**. The file-level criterion (no file over 600 lines) *is* met: the largest
file is `oto/tensile/legality.py` at 561 lines.

Print the current list before starting (this table is a snapshot):

```python
import ast
from pathlib import Path
for f in sorted(Path('oto').rglob('*.py')):
    for n in ast.walk(ast.parse(f.read_text())):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.end_lineno - n.lineno + 1 > 60:
                print(n.end_lineno - n.lineno + 1, f, n.lineno, n.name)
```

| # | function | location | lines | the seam to cut at |
|---|---|---|---|---|
| 1 | `mutate_and_feed` | oto/ledger/agent.py:248 | 227 | harvest -> filter -> emit |
| 2 | `run_auto` | oto/runners/auto.py:23 | 189 | floor-establish / tuning-loop / convergence |
| 3 | `iter_candidates` | oto/harness/candidate_pool.py:98 | 174 | wide / narrow / auto tiers |
| 4 | `run_phases` | oto/runners/phases.py:205 | 170 | skip/bypass policy vs the execution loop |
| 5 | `_load_ledger` | oto/metrics/run_status.py:112 | 163 | run-row read / chain resolve / record fold |
| 6 | `execute_phase` | oto/runners/benchmark.py:111 | 156 | record-pre / launch / record-post |
| 7 | `run_gfx900_reference` | oto/runners/reference.py:183 | 147 | run-dir swap vs delegation |
| 8 | `_compute_ab_verdicts` | oto/runners/reporting.py:123 | 140 | arm assembly / clock coverage / verdict build |
| 9 | `_run_tensile_benchmark` | oto/runners/benchmark.py:285 | 133 | argv+env / launch / poll / CSV collect |
| 10 | `_collect` | oto/metrics/ab_delta.py:45 | 131 | record fold vs per-cell statistics |
| 11 | `build_report` | oto/metrics/run_status.py:422 | 130 | report-dict assembly |
| 12 | `classify_outcome` | oto/ledger/mutator_outcomes.py:71 | 129 | outcome classification from on-disk CSVs |
| 13 | `_init_db` | oto/ledger/registry_core.py:103 | 127 | one `executescript` per table |
| 14 | `generate_family_phases` | oto/tensile/candidate_emission.py:158 | 124 | phase-id build vs width-clamp retry |
| 15 | `probe_phase_config` | oto/checks/tensile_build.py:157 | 121 | Tensile solution vs kernel-writer |
| 16 | `build` | oto/harness/resolve_cells.py:196 | 119 | per-cell resolution table build |
| 17 | `phase_survey` | oto/harness/kernel_db.py:134 | 115 | DB survey |
| 18 | `build_matrix` | oto/harness/regression_matrix.py:76 | 110 | matrix build |
| 19 | `_resume_deck` | oto/runners/reference.py:28 | 109 | rebuild vs reuse vs triage |
| 20 | `_pair_cells` | oto/metrics/ab_delta.py:247 | 101 | per-cell pairing (already partly cut) |
| 21 | `audit` | oto/metrics/ab_audit.py:110 | 101 | classification vs certainty grading |
| 22 | `main` | oto/tools/allruns.py:191 | 99 | one handler per subcommand, as in cli.py |
| 23 | `generate_acceptance_report` | oto/runners/reporting.py:263 | 98 | analytics vs timing vs verdicts |
| 24 | `converged` | oto/ledger/agent.py:149 | 98 | per-gate checks |
| 25 | `main` | oto/checks/tensile_build.py:455 | 98 | one handler per subcommand |
| 26 | `render` | oto/metrics/render_status.py:219 | 93 | section renderers |
| 27 | `main` | oto/tools/verify_run.py:306 | 91 | one handler per subcommand |
| 28 | `append_candidates_batch` | oto/tensile/candidate_emission.py:63 | 88 | collide/dedupe/append |
| 29 | `write_phase_config` | oto/tensile/config_writer.py:337 | 84 | gate / fork params / YAML dump |
| 30 | `synthesize_library` | oto/runners/synthesis.py:27 | 84 | emit / build / anti-alias / gate |
| 31 | `mutate_winner` | oto/tensile/candidate.py:91 | 80 | 1-knob vs 2-knob neighbours |
| 32 | `__init__` | oto/runners/driver.py:136 | 80 | wiring vs run-dir setup |
| 33 | `_compute_family_coverage` | oto/metrics/report.py:103 | 80 | per-family vs by-size |
| 34 | `main` | oto/harness/measure_vgprs.py:78 | 80 | one handler per subcommand |
| 35 | `reference_thresholds` | oto/metrics/coverage.py:49 | 78 | band vs bars |
| 36 | `_scan_dat_library` | oto/tensile/library.py:52 | 76 | scan vs assemble |
| 37 | `coverage_cells` | oto/metrics/coverage.py:161 | 74 | evidence vs state |
| 38 | `classify_cell_status` | oto/metrics/cell_status.py:24 | 74 | red vs orange vs graded |
| 39 | `_offer` | oto/harness/candidate_pool.py:115 | 74 | one row per tier |
| 40 | `_swizzle_defasible` | oto/tensile/gates/occupancy.py:322 | 73 | domain checks vs coupling |
| 41 | `select_deck` | oto/tools/consolidate_deck.py:210 | 70 | best vs sweep |
| 42 | `write_report` | oto/metrics/report.py:272 | 70 | JSON vs HTML delegation |
| 43 | `_family_matrix_rows` | oto/metrics/report_html.py:125 | 69 | family row vs size rows |
| 44 | `harvest` | oto/ledger/harvest.py:27 | 69 | score vs pick |
| 45 | `_reference_remaining` | oto/runners/reference.py:419 | 67 | universe vs newest-record scan |
| 46 | `load_phases_manifest` | oto/runners/phases.py:28 | 64 | deck vs overlay merge |
| 47 | `_fork_params` | oto/tensile/config_writer.py:177 | 63 | one block per knob family |
| 48 | `load_benchmark_csv` | oto/metrics/analytics.py:231 | 63 | parse vs validate |
| 49 | `read_thermals` | oto/metrics/read_thermals.py:29 | 62 | read vs summarise |
| 50 | `telemetry` | oto/tools/verify_run.py:173 | 61 | filter stages |
| 51 | `_coverage_matrix_section` | oto/metrics/report_sections.py:227 | 61 | header vs body |

Approach per function: cut where a sub-result first becomes available — the same
cut that was proved safe for the 12+ functions already decomposed this round —
then re-run `python3 plans/verify_all.py`, which is the guard that the cut did
not change behaviour.

### PENDING — known slop observed during the move

* **`oto/checks/db.py`, `oto/checks/retirement.py`** — two throwaway ad-hoc
  sqlite scripts that used to execute at *import* time (no `main()` guard).
  Wrapped in `main()` this round so importing the package is side-effect free,
  but the bodies are still one linear script each; they are not real checks and
  should either become proper checks or be deleted.
* **`oto/tools/consolidate_deck.py:119`** — its docstring still cites
  `scheduler.FAMILY_BYTES_PER_ELEMENT`, a module that no longer exists under
  that name (it is `oto.tensile.gates.vgpr_model`).
* **`oto/ledger/harvest.py:136`** — same: a comment cites "scheduler family
  decks"; the module is now `oto.tensile.decks`.
* **`oto/tensile/candidate.py:51`** — `_ = (depth_u, dtype_char, tile_dims,
  FAMILY_DTYPE_CHAR, NUM_CUS)` exists purely to keep linters quiet about
  re-exports. The `__all__` list already does that job; the throwaway tuple
  should go.
* **`oto/tensile/candidate.py` `parse_tensile_shape`** — a lazily-delegated
  re-export for the pre-split import surface. Its only caller is the test suite;
  once the tests import from `config_writer` it can be deleted.
* **`oto/harness/candidate_pool.py`** — `fingerprint_config` is imported but the
  module has its own `_fingerprint`; one of the two is dead.
* **duplicated dark-palette CSS** in `oto/metrics/report_css.py`
  (`DASHBOARD_CSS` declares the same 23 custom properties twice: once as
  `[data-theme="dark"]`, once inside `prefers-color-scheme`). Deliberate, and
  only because collapsing it changes which theme wins when an operator has
  explicitly pinned a light theme. If that precedence is ever worked out, this
  is the one place to do it.

### NOT ATTEMPTED (deliberate)

* `oto/device/profile.py` and `oto/device/profile_registry.py` were **not**
  created. The plan marks them as the Refactor 2 seam; creating stubs now would
  be scaffolding with no caller.
* `harness/` moved to `oto/harness/`, but `tests/` stays at the repo root —
  the plan says tests move last.
