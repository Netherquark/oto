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
arm, ±5% tie = parity.

**Status:** `gfx900_ref_20260925_152942` = 1,073/2,285 executed, 116 failed,
1,096 unattempted → 1,212 phases to resume (~1.1 day). `--auto` gates all tuning
behind floor completion (`_reference_remaining() == 0`).

**Residue/evidence:** `gfx90c_results/registry.db` 3,369 measured rows stamped
`cell_key`/`arm`/`kernel_key`; `idx_cell_key` index exists in the live registry
only — `registry.py` does not create it, so a fresh DB would miss it.

## 4.2 One-shot driver + --auto (RESOLVED — 2026-09-13)

**Mechanism:** `port_tensile.py` + `phases.yaml` manifest + 7 modules (`registry.py`, `report.py`, `analytics.py`, `policy.py`, `scheduler.py`, `agent.py`, `gfx90c_common.py`) fully implemented and unit-tested. `--auto` convergence loop operational with deterministic mutate-≤2-knobs candidate generation.

## 4.3 28-family native coverage (RESOLVED — 2026-09-13)

**Mechanism (T3):** 28-family native coverage generated in `phases.yaml` spanning all 7 families `{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}` across 4   contraction patterns `{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}` with anchor problem shapes (304 candidate configs: 232 family + 72 auto; re-derived to **410 phases** 2026-09-26).

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
- `phases.yaml` fully populated with 28 native families across 4 contraction patterns (228 clean targets; the live manifest = **410 phases** as of 2026-09-26, see `results.md` §1).
- Added `--dry-run` to inspect matched candidate targets before hardware execution.

## 4.13 Parallel Clang Build, Cooldown Key Handling & Early Quit Reports (RESOLVED — 2026-09-13)

**Mechanism:**
- Multi-threaded assembly compilation enabled by setting `CpuThreads: min(os.cpu_count(), 16)` in generated YAMLs and `make -j`.
- Fixed Tensile `ForkParameters` emission from `MacroTile0`/`MacroTile1` to valid schema `MacroTile: [[M0, M1, DepthU]]` fixing CC/DD configuration parsing.
- Integrated non-blocking `select.select()` listener in `_apply_cooldown()` so `'s'` skips cooldown sleep and `'q'` quits immediately.
- Ensured `acceptance_report.json` and `acceptance_report.html` are generated and persisted to `gfx90c_results/` even on early termination via `'q'` or interruption.