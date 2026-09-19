# Adversarial Review: attempt2 harness/pipeline baseline & audit plan

**Purpose:** carry the prior-campaign audit findings INTO attempt2 so the new python
driver (port_tensile.py per implementation_plan.md §The Driver Architecture)
inherits the FIXED state, not the bugs. Conclusions below are the frozen prior
verdicts (each PoC-verified) — the only sanctioned prior material is
`prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`; this file is
self-contained. Status: carried-in fixed-state must not regress; re-audit the
driver before it is trusted for `--auto`.

## 1. Sources

Frozen prior-campaign audit verdicts (v1 2026-09-11 §1-4 + v2 2026-09-12 §5),
absorbed into `prior_RESEARCH_ARCHIVE.md`.

| Finding | Prior status | attempt2 posture |
|---|---|---|
| pipefail fragility in `$(...|...)` (SIGPIPE/141 on healthy zero-match) | FIXED (`|| true` / `set +e` isolation) | driver is python; must not reintroduce shell pipes where status matters |
| unmanaged concurrency / joblib+shared-temp races | FIXED (isolated workdirs + advisory locking) | single-writer process; no fork-lock, no parallel temp writers |
| flawed ruler normalization (4 bugs: max-anchored squares, cross-dtype geo-mean leaking DDR factor, dt-string key no-op, missing → 1.0 fabrication) | FIXED (bound-class median, keyed (dt,cls), missing → reported not inferred) | ruler-adjusted winner semantics unchanged, byte-for-byte if possible |
| half-baked telemetry + 1000× sclk_khz unit error (Hz under kHz label) | FIXED (continuous sampler, Hz, header-in-CSV) | telemetry header-in-file; canonical Hz/µW/mC/% |
| conflated lifecycle states (retire vs dominate vs peak) with zero provenance | FIXED (3-tier, hardcoded list removed, registry lineage) | policy.should_run + auto_retire with ≥2-run gate |
| blind-union synthesis merge with no per-cell regression filter | **STILL OPEN / deferred** | agent.harvest() admission gate (§4 below) |

## 2. What the attempt2 driver must not reintroduce

- **No printf-JSON:** every record byte = `json.dumps(dict)` through the single
  append path. Never `"…%s"` interpolation into JSONL (prior-campaign §5.1 — value
  with `"`, `\`, or embedded newline corrupted live records; 2/1283 already
  broken).
- **No fork-lock:** single-writer process; SQLite WAL mode; INSERT-only `records`
  table with `json.dumps` payload (`knowledge_base.md` §10.2). No sibling `.lock`
  files, no fd-9 `flock(1)` dance, no retry state machines.
- **No inferred missing controls:** missing (dt,cls) ruler or un-gated telemetry
  window → "not computable / unadjusted", never 1.0 fabrication and never a
  cross-dtype factor leak (v1 §2.3).
- **No hardcoded retirement lists:** the 3-tier model is evidence-only (registry
  rows). No `PHASE_RETIRE`-style reserved set compiled into code; spoof / peak
  are NEVER a retire signal (guardrail: gfx900 = floor).
- **No self-terminating run-all:** phase 1 is first-ever-run-only floor; every
  phase runs from the manifest unless `policy.should_run` says otherwise
  (tier-1 fp-less retire → tier-2 (phase,fp) retire → phase-1-once → identical-fp
  skip opt-in).
- **No hwmon parent-glob:** read `hwmon[0-9]*` paths via pathlib; never
  `find -name 'hwmon*'` (v2 §5.2 — parent dir matched first → all-NA rows while
  `gpu_busy_percent` still worked, masking the failure).
- **No `.hdr` sidecar:** telemetry header written INSIDE telemetry.csv; the v1
  sidecar was never consumed by any reader — equal-defect junk file.
- **No power1_average-only:** fallback order `power1_input` → `power1_average`;
  Cezanne hwmon4 exposes `power1_input` only (v2 §5.2).

## 3. Audit checklist for port_tensile.py

- [ ] **Manifest order == execution.** phases.yaml order is the run order;
  pytest asserts count + order + reserved-gap exclusion. No awk header self-check
  (manifest is data, not code comments).
- [ ] **Single-writer SQLite.** Exactly one `append_record()` with SQLite INSERT,
  WAL mode, one open handle per process; `records` INSERT-only.
- [ ] **`json.dumps` everywhere.** No printf-JSON, no `json_str()` subprocess in
  any writer (registry, experiment records, retire, telemetry).
- [ ] **Telemetry header-in-file.** First row is the header inside telemetry.csv;
  sampler reads `hwmon[0-9]*`; `power1_input` fallback; units canonical Hz/µW/
  mC/% .
- [ ] **PEAK single-source import.** `from gfx90c_common import PEAK_GFLOPS` —
  no duplicated dict in the driver; BF16/INT8 = 1613 single-rate.
- [ ] **policy.should_run unit-test matrix.** Re-run the 4-case matrix from the
  prior policy spec: empty-registry→RUN (`--phases 1 31`), prior PASS fp→SKIP,
  phase-1-once disabled→RUN, phase-scope-exempt→RUN. New cases: tier-1
  fp-less record→SKIP; tier-2 (phase,fp)→SKIP.
- [ ] **Detached + killable GPU phases.** `setsid` process groups; 's' kills the
  CURRENT phase and continues, 'q' quits the run; Ctrl+C kills the in-flight
  benchmark group; EXIT trap stops telemetry idempotently.
- [ ] **Finite per-phase timeout default.** `PHASE_TIMEOUT_S` default must be
      finite — generic runaway protection, never a size-specific special case.

## 4. Known-open exposures for attempt2

- **Synthesis blind union** (prior §2.6/§5.8): merged library is union of
  per-cell winners with no per-cell regression filter vs spoof. Carried;
  admitted only via the agent admission gate (incomplete_work §4.8).
- **Retire-evidence linkage:** zero trustworthy `retire` records yet; the 3
  prior auto-retires are single-invocation (need ≥2 independent runs/cell —
  incomplete_work §4.6). The RETIRED mirror stub still lacks its source run_id
  (prior §5.3 promise: join by run_id + reason on the next real retirement).
- **2 corrupt legacy JSONL records** (v2 §5.1) remain in place — append-only,
  changelog §0 rule. Readers must tolerate/triage, never rewrite in place.
- **FPGA/APU wedge hazard at sustained 2048³+:** a wedge begins as idle-busy 0%
  at 400 MHz (run_20260912_085712 root cause). Always-on: cooldown between GPU
  phases (30 s latch-off for first benchmark), continuous telemetry so a wedge
  is visible, and the kill guards above.
- **Occupancy cap (T9):** VGPR pressure + grid underfill limits achieved
  utilization to ~69–77% of pipe — the performance objective to raise, not a
  hazard (gfx90c_theoretical_limits.md §7).

## 5. Acceptance criteria unchanged

- **Phase-0 10/10 gates:** the preflight gate set must pass 10/10 before any
  benchmark phase runs (arch/device/tensileness, manifest parse, registry open,
  telemetry probe, cooldown wiring).
- **RED anti-alias re-assert vs gfx900 leaks:** a RED cell is RED only against
  a real native gfx90c measurement, never against a gfx900-spoof or CPU-fallback
  number; re-assert isa scheduling per cell so no spoof leaks into the native
  determination. Convergence = no RED cells below threshold, or budget spent.
- **Native-vs-spoof, same-run, ruler-adjusted, median-of-seeds, ties = parity:**
  superiority is demonstrated per cell via a same-run A/B (`--phases 1 31` vs
  `--phases 20 25` pair),
  ruler-adjusted (bound-class median), median-of-seeds; a tie is PARITY, not a
  regression, and not a win. Every metric must meet this or the acceptance is
  not claimed.