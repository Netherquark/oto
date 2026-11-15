# Adversarial Review: user-run expert audit of the oto repo
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


**Purpose:** this file owns the **user-run external expert-agent review** of the
repository. It is NOT a driver-internal quality gate. When the user wants a
correctness/hardware audit, the USER launches an expert agent (out-of-band,
outside the deterministic convergence loop) to review the repo and records the
findings here. The review targets **memory leaks, race conditions, logical bugs,
data-integrity errors, deadlocks, resource leaks, error-path bugs, and other
correctness defects** in the codebase. Findings are recorded back into this file
(§0), triaged, and feed fixes in `docs/implementation_plan.md` (Triaged fixes) and
`changelog.md`.

Hard lines (mirror `claude.md` guardrails):

- **Out-of-band, add-only.** The expert audit never runs inside the benchmark
  loop — the same class of out-of-band input as LLM-proposed candidate rows
  (`oto agent consult`, or an out-of-band user-invoked LLM): additive, never an
  in-loop gate or verdict.
- **Evidence-based only.** Findings must cite live repo/source + logs + DB, under
  the `live repo → owner MDs → agent logs → old summaries` precedence. No
  model-memory claims.
- **Record before fixing.** Findings are logged into §0 the moment they are
  established and are only closed via triage; fixes land afterwards via the
  owning MD (implementation_plan / changelog). Findings are append-only — never
  rewritten in place, only annotated.

Status: a user-run expert audit of the codebase (memory / races / logic) is the
operating mode of this document. §1–§5 below are frozen prior verdicts (each
PoC-verified, sourced `prior_*`) and must not regress.

## 0. Findings register (user-run expert audits)

| ID | Audit date | Finding (`file:line`) | Class | Severity | Status / Triage | Evidence |
|---|---|---|---|---|---|---|
| _open_ | | | | | | |

Classes: `MEM` memory leak/lifetime · `RACE` race condition/deadlock ·
`LOGIC` logical bug/wrong result · `DATA` data integrity/corruption ·
`RESOURCE` fd/thread/process leak · `EDGE` boundary/error path ·
`TELEMETRY` measurement trust.

How to run an audit:

1. User invokes an expert agent (or several in parallel) over the repo.
2. Scope = the whole `oto` suite (`bin/oto` / `oto/runners/driver.py` +
   `oto/ledger/registry.py`,
   `oto/tensile/candidate.py`, `oto/metrics/cell_policy.py`,
   `oto/metrics/benchmark_analytics.py`, `oto/ledger/convergence_agent.py`, `oto/metrics/telemetry.py`,
   `oto/metrics/acceptance_report.py`, `oto/device/loader.py`) plus the docs/logs it reads and
   writes.
3. Agent reports each finding as an exact `file:line` with repro/evidence; new
   entries are appended to the register. Existing entries are never edited in
   place — only their status cell is annotated.
4. User triages: **Accepted** → fix specified in `docs/implementation_plan.md`
   Triaged fixes; **Rejected** → rationale recorded; **Pending** → left for the
   next audit pass.

## 1. Sources

Frozen prior audit verdicts (v1 §1-4 + v2 §5), sourced in `docs/gfx90c_tuning_guide.md` §14 (`archive/prior_research_archive.md`, untracked).

| Finding | Prior status | oto posture |
|---|---|---|
| pipefail fragility in `$(...|...)` (SIGPIPE/141 on healthy zero-match) | FIXED (`|| true` / `set +e` isolation) | driver is python; must not reintroduce shell pipes where status matters |
| unmanaged concurrency / joblib+shared-temp races | FIXED (isolated workdirs + advisory locking) | single-writer process; no fork-lock, no parallel temp writers |
| flawed ruler normalization (4 bugs: max-anchored squares, cross-dtype geo-mean leaking DDR factor, dt-string key no-op, missing → 1.0 fabrication) | FIXED (bound-class median, keyed (dt,cls), missing → reported not inferred) | ruler-adjusted winner semantics unchanged, byte-for-byte if possible |
| half-baked telemetry + 1000× sclk_khz unit error (Hz under kHz label) | FIXED (continuous sampler, Hz, header-in-CSV) | telemetry header-in-file; canonical Hz/µW/mC/% |
| conflated lifecycle states (retire vs dominate vs peak) with zero provenance | FIXED (evidence-only single Tier-2 path, hardcoded list removed, registry lineage) | policy.should_run + `check_retirement_eligibility` with ≥2-run gate |
| blind-union synthesis merge with no per-cell regression filter | **MITIGATED** (admission gate agent.harvest() LCB + best-effort carve chain with provenance) | agent.harvest() admission gate (§4 below) |

## 2. What the oto driver must not reintroduce

The code-level architecture prohibitions (no hardcoded retirement lists, no
hwmon parent-glob, no `.hdr` sidecar, no `power1_average`-only) live in
`oto/ledger/registry_core.py`. The four that are policy rather than code stay:

- **No printf-JSON:** every record byte = `json.dumps(dict)` through the single
  append path. Never `"…%s"` interpolation into JSONL (frozen §5.1 — value
  with `"`, `\`, or embedded newline corrupted live records; 2/1283 already
  broken).
- **No fork-lock:** single-writer process; SQLite WAL mode; INSERT-only `records`
  table with `json.dumps` payload (`docs/gfx90c_knowledge_base.md` §10.2). No sibling `.lock`
  files, no fd-9 `flock(1)` dance, no retry state machines.
- **No inferred missing controls:** missing (dt,cls) ruler or un-gated telemetry
  window → "not computable / unadjusted", never 1.0 fabrication and never a
  cross-dtype factor leak (v1 §2.3).
- **No self-terminating run-all:** the spoof floor = the dedicated `gfx900_ref_*`
  chain (recalled, never a manifest phase-1 slot); every phase runs from the
  manifest unless `policy.should_run` says otherwise (tier-1 fp-less retire →
  tier-2 (phase,fp) retire → identical-fp skip opt-in).

## 3. Audit checklist for the driver

- [x] **Manifest order == execution.** phases.yaml order is the run order;
  `tests/test_manifest_order.py` locks it (loader preserves file order; round-trip
  stable; phase ids unique and count shipped-38). No awk header self-check
  (manifest is data, not code comments). Attested 2026-11-15.
- [x] **Single-writer SQLite.** Exactly one `append_record()` with SQLite INSERT,
  WAL mode, one open handle per process; `records` INSERT-only
  (`oto/ledger/registry_queries.py::append_record`). Attested 2026-11-15.
- [x] **`json.dumps` everywhere.** No printf-JSON, no `json_str()` subprocess in
  any writer (registry, registry_queries, registry_core verified line-by-line;
  zero printf-`%"s"` interpolation into JSON anywhere in the tree). Attested 2026-11-15.
- [x] **Telemetry header-in-file.** First row is the header inside telemetry.csv;
  sampler reads `hwmon[0-9]*`; `power1_input` fallback; units canonical Hz/µW/
  mC/%; reader tolerates the presence (or absence) of the header explicitly and
  reports `header_missing` instead of inventing values. Attested 2026-11-15.
- [x] **PEAK single-source import.** The peak table lives only in
  `oto.device.loader` (profile JSON); the `oto.device.peaks` shim is deleted; the
  only remaining `peak_gflops` key is the dataclass field on the profile model.
  Attested 2026-11-15.
- [x] **policy.should_run unit-test matrix.** `tests/test_outcome_writeback.py`
  covers the identical-fp skip matrix; the full branch matrix — scope hit/miss,
  tier-1 (fp-less phase) retired, tier-2 (phase, fp) retired, empty-registry→RUN —
  is locked by `tests/test_policy_should_run.py` (9 cases, all passing).
  Attested 2026-11-15.
- [x] **Detached + killable GPU phases.** `setsid` process groups in
  `benchmark.benchmark` (`os.setsid()`), kill-on-signal paths in `runners/driver.py`
  ('s' skip current phase, 'e' end after current phase, 'q' quit, Ctrl+C kills
  the in-flight group; telemetry's existence is gated on the process staying up).
  Attested 2026-11-15.
- [x] **Finite per-phase timeout default.** `--phase-timeout` defaults to 3600 s
  (`oto/runners/stage_flags.py:169`); `TensileDriver(phase_timeout_s=3600)` is
  the runner default. Never size-specific. Attested 2026-11-15.

## 4. Known-open exposures for oto

- **Synthesis blind union** (prior §2.6/§5.8): merged library is union of
  per-cell winners with no per-cell regression filter vs spoof. Carried;
  admitted only via the agent.harvest() admission gate (`oto/ledger/harvest.py`,
  LCB parent selection; `oto/tensile/best_effort_library.py::build_best_library`
  native→fallback→floor chain). Low-blast-radius: the gate is explicit, and
  every admitted cell's provenance is written into the best-library manifest.
- **Retire-evidence linkage:** zero trustworthy `retire` records yet; the 3
  existing auto-retires are single-invocation (need ≥2 independent runs/cell —
  incomplete_work §4.5, RESOLVED). The retired mirror stub still lacks its source
  run_id (frozen §5.3 promise: join by run_id + reason on the next real
  retirement).
- **2 corrupt frozen JSONL records** (v2 §5.1) remain in place — append-only,
  changelog §0 rule. Readers must tolerate/triage, never rewrite in place.
- **FPGA/APU wedge hazard at sustained 2048³+:** a wedge begins as idle-busy 0%
  at 400 MHz (run_20260912_085712 root cause). Always-on: cooldown between GPU
  phases (30 s latch-off for first benchmark), continuous telemetry so a wedge
  is visible, and the kill guards above.
- **Occupancy cap (T9):** VGPR pressure + grid underfill limits achieved
  utilization to ~69–77% of pipe — the performance objective to raise, not a
  hazard (docs/gfx90c_theoretical_limits.md §7).

## 5. Acceptance criteria unchanged

- **Phase-0 10/10 gates:** the preflight gate set must pass 10/10 before any
  benchmark phase runs (arch/device/tensileness, manifest parse, registry open,
  telemetry probe, cooldown wiring).
- **RED anti-alias re-assert vs gfx900 leaks:** a RED cell is RED only against
  a real native gfx90c measurement, never against a gfx900-spoof or CPU-fallback
  number; re-assert isa scheduling per cell so no spoof leaks into the native
  determination. Convergence = no RED cells below threshold, or budget spent.
- **Native-vs-spoof, recalled-floor, ruler-adjusted, median-of-seeds, ties = parity:**
  superiority is demonstrated per workload cell vs the recalled `gfx900_ref_*`
  chain (dedicated floor runs, `--resume` continuations — never a phase-1 slot),
  ruler-adjusted (bound-class median), median-of-seeds; a tie is PARITY, not a
  regression, and not a win. Every metric must meet this or the acceptance is
  not claimed.

## 6. Unapproved drifts

Any change that lands without explicit approval (e.g. treating
`/tmp/opencode/*_fixed.py` as the spec) is a drift and must be logged here
before it is trusted. Drifts are addressed in order: log → user triage →
approved fix/cherry-pick → `changelog.md` entry. Tracked jointly with
`incomplete_work.md` §4.9.