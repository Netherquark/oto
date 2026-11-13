# Test optimization plan (CPU-only, no GPU)

**Status: EXECUTED (2026-10-21).** The full suite went from **20 m 01 s with
5 failures** to **2 m 10 s, 902 passed, 0 failed** (1 m 27 s with `-n auto`).
The wins were not the ones the plan guessed: the dominant cost was *YAML
parsing*, not the gates, and the five failures were a mutator that had stopped
exploring the axes the cells need.

## What was measured (before)

| phase | wall clock | what it was |
|---|---|---|
| full suite | 20 m 01 s | 899 passed, **5 failed** (pre-existing) |
| `test_deck_review` | 175 s + 98 s | three corpus walks |
| `test_coverage_phase3` | 168 s + 4 x 85 s | five corpus walks |
| `test_generate_candidates` | 60 s | the deck, re-parsed ~40 times |
| `test_legal_slow` | 77 s | one corpus walk |

## What was done

1. **The canonical YAML reader** (`oto/yamlio.py`). PyYAML's pure-Python
   `safe_load` costs 0.27 s for `phases.yaml`; libyaml (which is installed)
   costs 0.03 s, and the content-stamped cache removes the repeats. Every
   `yaml.safe_load` in `oto/` now goes through it. **This was the whole
   win**: `test_generate_candidates` fell from 68.7 s to 2.9 s, and the
   suite from 20 m to 5 m 41 s.
2. **The corpus reads are memoised.** `oto.metrics.ab_records.arm_record_sets`
   walks every run directory's CSVs plus the registry (~76 s) and every
   coverage test wanted it; it is now memoised on a corpus stamp (run count,
   newest run mtime, registry size and mtime). `oto.harness.kernel_db`
   gained `read_kernel_db` (parsed, memoised on the same idea) and the four
   readers that parsed the 18 MB JSON themselves now share it.
3. **The gates are memoised** (`oto/tensile/gates/memo.py`). The three gate
   families are pure functions of their config, so `memo_gate` caches them by
   content. A config that changes gets a new verdict; a config that does not
   gets the old one. Bounded at 50 000 entries.
4. **xdist, with the serial rule** (`tests/conftest.py`, `pytest.ini`).
   `pytest -n auto` runs the suite in 1 m 27 s. A test that writes into the
   repo tree must carry `@pytest.mark.serial`; under a distributed run it is
   skipped with the reason spelled out, so the next such test is safe by
   default rather than by remembering. Nothing carries the marker today
   (every write in the suite goes to a tmp dir) -- the mechanism is there for
   the first test that does not.
5. **The fast path for the tree-walking guards.** `OTO_GUARD_FILES=1` narrows
   `test_function_length`, `test_pyflakes`, `test_ruff`, `test_py_compile` and
   `test_file_length` to the files git reports as changed: 2.11 s -> 0.70 s. The full scan stays
   the default, because a guard that only looks at what you touched is not a
   guard.
6. **The live run panel** (`oto.metrics.render_status`, `oto.runners.phases`).
   The panel now shows the **per-tier bars** (ILLEGAL / UNDER-SPECIFIED /
   UNREPRODUCIBLE: decided of total) instead of only the aggregate
   "decided 720/2285", and the driver **repaints it the moment a phase
   lands** rather than up to an interval later -- a long run spends most of
   its time in one tier, and the aggregate alone does not say where.
   `pytest -n auto` gives the *test* run a live progress line for free.
7. **The preflight marker.** `pytest -m preflight` is the subset the
   overnight checklist runs (177 tests, 36 s). The file list lives in
   `tests/conftest.py`, so the marker and the checklist cannot drift.

## The five failures (pre-existing, found by the suite)

They were *not* test-suite bugs -- they were real defects the suite had been
carrying since the 2026-10-21 knob batch:

- **`GlobalSplitU` was never drawn again.** The narrow mutation pass walked
  `FORWARD_KNOB_DOMAINS` in dict order, and the ten knobs that batch added
  (pads, asserts, non-temporal, MaxOccupancy...) took the whole budget
  before the wave-fill lever was reached. The mutator was spending every
  draw on pads. The pass now visits the knobs in a **seeded shuffle**,
  round-robin over their legal values, and takes at most half the budget
  (the wide pass, which is the only one that moves the *geometry*, gets the
  rest, with the remainder as a top-up for the families whose DB has no
  donor tile). SS and DD draw GSU>1 again, and the wide pass contributes
  donor tiles again.
- **The `nt_budget` rule was "rejected" on a wrong measurement.** It was
  probed on 2026-10-18 and refused because it seemed to refuse a phase
  Tensile built (Z tt2x2 at 64x64, 1024 threads, "71 VGPRs"). That kernel
  emits **63** VGPRs (read out of its own code object), which fits the 64 a
  1024-thread workgroup has. With the measured table corrected the rule is
  *adopted* -- it is exactly the per-thread occupancy limit the gate now
  enforces, and it fires on the 8 phases that died with error 4 in the
  2026-10-20 run.
- **`NLCA=-1`** is legal (Tensile allows `range(-1, 65)`) and the repo's
  gate handles it; the test still pinned the old domain.

## How to run

```
pytest                     # the whole suite, serial (2 m 10 s)
pytest -n auto             # the whole suite, distributed (1 m 27 s)
pytest -m preflight        # the pre-run subset (36 s)
OTO_GUARD_FILES=1 pytest tests/test_function_length.py tests/test_pyflakes.py tests/test_ruff.py tests/test_py_compile.py tests/test_file_length.py
```

The preflight subset is *faster serial* (36 s) than distributed (44 s): the
xdist worker startup costs more than the subset saves. Use `-n auto` for the
full suite.

## Still open

- The remaining hot spots are the corpus walks themselves (18 s in
  `test_verify_run`, 16 s in one coverage test, 6.7 s in
  `test_asm_occupancy`): they read the *run directories*, not the cached
  artifacts. A corpus-wide index (one pass, many readers) would fold them
  into the same memo.
- The `serial` marker is unused: the first test that writes into the repo
  tree should carry it, and the mechanism is already in place.
- The live progress bar is **done** (below): the panel repaints when a phase
  lands, and it shows the per-tier bars.
