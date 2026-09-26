# fix.md — canonical candidate labeling + spoof↔native cell mapping (applied)

Status: **APPLIED 2026-09-26** (commits `ccd7fed` + `58245c8`; see `changelog.md`).
Steps 0–6 landed: floor-binding fix (30 per-cell verdicts), `cell_key`/`arm`/
`kernel_key` stamping, one-time backfill (3,369 rows), per-cell pairing rewrite,
`idx_cell_key` index (live DB only). This fixes the drift between the CURRENT gfx900 spoof
run and CURRENT native candidates in `gfx90c_results/registry.db`, and makes the A/B
comparison in the acceptance-report flow compare by **workload cell = (family / dtype /
shape)** — exactly the arm-vs-arm mapping in `/tmp/opencode/gfx900_spoof_vs_native_A_B.html`.

Rollback point for anything applied to registry.db: verified backup
`oto/backups/2026-09-26_preanalysis/main/registry.db`
(sha `64ebdaa2cdd432ab4871bb7fa64fd00b032b9a6485e94be71276776007686b6a`).

## 1. The problem (today, current state only)

A spoof cell and its native same-workload counterpart cannot be joined fast or cleanly:

- Spoof records are reachable by `fp`/phase-id; native records are keyed by
  `(dtype, shape, fingerprint, kernel_name, config)`.
- Kernel naming has drifted between the arms (spoof emits gfx900 spoof names, native
  emits isa names) — so identical-kernel matching is impossible for most of the deck and,
  critically, is **irrelevant**: the comparison that matters is same-workload (family/dtype
  + shape), best kernel of each arm, winner by GFLOPS.
- The acceptance flow (`analytics.compute_native_vs_spoof_delta`) already keeps the
  **native side as best-per-(dtype, shape)** but keeps the **spoof side split per
  fingerprint**, so the report is per-spoof-kernel-fp rather than per-cell, and it must
  re-derive identity from loose text on every run.

## 2. Canonical labeling/naming scheme — one label set, both arms

Every measured candidate (spoof AND native) is saved to `registry.db` with three fields:

| field | value | purpose |
|---|---|---|
| `cell_key` | `"<FAMILY>:<SHAPE>"`, e.g. `SS:1024` | **the mapping key** — workload identity |
| `kernel_key` | `"<FAMILY>/<pattern>/MT<M0>x<M1>/TT<T0>x<T1>/VW<V>/DU<D>/GSU<G>"` | drill-down only; cites *which* kernel won, never used to pair |
| `arm` | `"spoof"` \| `"native"` | side of the comparison |

Rules:
- `<FAMILY>` ∈ {SS, DD, HH, CC, ZZ, HH_HPA, HS_HPA}; `<SHAPE>` = the **actual executed**
  batched cube side M=N=L (`1000`, `1024`, …) — derived from the executed shape, never
  from a stale template.
- `dtype` (S/D/H/C/Z) stays parallel; `cell_key` and `(dtype, FAMILY, shape)` are
  equivalent views of the same key.
- `kernel_key` changes allowed freely (knobs evolve); the pair never depends on it.
- Optional `sclk_mhz` recorded at bench time enables `GFLOPS_throttle_adjusted =
  GFLOPS * 1800/sclk_mhz` (the "throttle-adjusted" variant).

Example `benchmark_result` row (current registry.db schema, `data` JSON):

```json
{
  "type": "benchmark_result",
  "run_id": "run_...",
  "phase_id": "phase_ss_isa_...",
  "arm": "native",
  "cell_key": "SS:1024",
  "kernel_key": "SS/Ailk_Bjlk/MT64x64/TT4x4/VW2/DU16/GSU1",
  "family": "SS",
  "dtype": "S",
  "shape": "1024x1024x1024",
  "GFLOPS": 875.0,
  "sclk_mhz": 1800,
  "GFLOPS_throttle_adjusted": 875.0,
  "seed_index": 0
}
```

## 3. Mapping — spoof cell → native counterpart (current acceptance flow)

Replace the fp-dimension pairing in `analytics.compute_native_vs_spoof_delta` with a pure
per-cell compare; both sides aggregate over **all kernels measured at that cell**, which is
precisely the HTML above:

```
spoof_side  = reference chain (recalled gfx900_ref_*) benchmark_result rows, arm="spoof"
native_side = registry.db benchmark_result rows,                  arm="native"

cell_stats[cell_key] = {
    "n_kernels", "n_seeds",
    "best":        max(GFLOPS) over every row in the cell,
    "median":      median of per-kernel medians over every row in the cell,
    "throttle":    median of GFLOPS_throttle_adjusted over every row in the cell,
}

for cell_key in set(spoof_cells) & set(native_cells):
    winner = SPOOF/NATIVE/TIE    # by chosen agg, tie_band as today
    ratio  = spoof_agg / native_agg
    cite   = kernel_key + phase_id of the winning row (both arms)
```

Signature change: `compute_native_vs_spoof_delta(native_records, spoof_records,
agg="median", tie_band_pct=5.0)` where `agg ∈ {"best","median","throttle"}` selects the
spoof baseline metric; the native side stays best-of-cell median per today's semantics.
The verdict feed for `report.py`/acceptance dashboard is unchanged (per-cell verdicts),
only the unit of comparison moves from (dtype, shape, fp) to (family, dtype, shape).

Fast lookup: `cell_key` is emitted in stone in every row, so per-cell stats are a single
group-by — `SELECT cell_key, max(GFLOPS), ... FROM records WHERE arm='native' GROUP BY
cell_key` — no name parsing. Add:

```sql
CREATE INDEX idx_cell_key ON records(json_extract(data, '$.cell_key'));
```

(SQLite expression-indexes JSON extracts on ≥3.38; fallback is a maintained
`cell_rank(run_id, arm, cell_key, best_gflops, median_gflops)` KV cache updated on save.)

## 4. Implementation plan

0. **FIX A COMMITTED BUG (c4e4a85) first — verified by PoC B0:** `port_tensile.py`
   `_compute_ab_verdicts()` binds the spoof floor records from the WRONG tuple slot:
   `ref_records, _ = self._ab_records_from_csv(ref_dir, force_arm="spoof")` — with
   `force_arm="spoof"` all records land in the SECOND element, so `ref_records` is the
   empty native list and the A/B floor is silently dropped. Current deployed report
   shows "0 WIN / 0 TIE / 0 LOSS" because of this. Correct binding:
   `_ref_native, ref_records = self._ab_records_from_csv(ref_dir, force_arm="spoof")`.
   After the fix the same run yields 30 per-cell verdicts (18 WIN / 9 TIE / 3 LOSS) —
   see PoC A3.
1. **Helpers** (`gfx90c_common.py`): `cell_key(family, shape_side)`, `kernel_key(pattern,
   mt0, mt1, tt0, tt1, vw, du, gsu)`, `shape_side("NxNxL") -> N` (cube assert).
2. **Stamp at save time** (`port_tensile.py` `execute_phase` benchmark_result emit + spoof
   reference emission): write `arm`, `cell_key`, `kernel_key` (+ `sclk_mhz` when
   telemetry is live) with every row. Both arms use the same two helpers — this is the
   drift kill switch going forward.
3. **One-time backfill of CURRENT registry.db only**: a single Python pass over existing
   `benchmark_result` rows derives `cell_key` from `config.FamilyLabel`/`dtype` + the
   actual `shape` field and stamps it via `UPDATE ... SET data = json_set(...)`; also
   stamps `arm` (spoof = rows whose phase is under `gfx900_ref_*` runs, else native).
   The 24h spoof run's 4896-row native draft corpus is all covered. No archaeology of any
   historical attempt is performed.
4. **Rewrite the pairing** (`analytics.py` `compute_native_vs_spoof_delta`): per
   (family/dtype, shape) on BOTH sides; deltas carry `best`/`median`/`throttle` native +
   winning `kernel_key`s for citation.
5. **Index/cache** for the O(1) cell lookup (index above; `cell_rank` cache if the sqlite
   JSON-extract index is unavailable).
6. **Validate**: regenerate the acceptance report for `run_20260920_235815` and confirm the
   per-cell winners/ratios match the 20-cell arm-vs-arm gold set from the temp tool
   (HH@256 native, SS@2048 spoof at 164%, etc.), then re-run `--report` for the verified
   verdicts.

## 5. Explicitly NOT doing

- No excavation/relabeling of any previous attempt's data or DBs; the label is stamped
  forward from today and a backfill only normalizes CURRENT `registry.db` rows.
- No requirement that spoof and native kernels be identical to compare — pairing is
  strictly `(family/dtype, shape)`; identicalness (kernel_key) is citation only.