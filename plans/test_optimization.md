# Test optimization plan (CPU-only, no GPU)

## Slowest files (measured 2026-10-21)
- tests/test_generate_candidates.py  ~60s (gate-clean over LADDER/PLAN_BATCH/FRONTIER)
- tests/test_tile_frontier.py        ~?s (exhaustive legality sweep)
- tests/test_corpus_census.py        ~?s
- tests/test_occupancy_gate.py       ~?s (corpus-wide measured totals)
- tests/test_interactive_keys.py     ~1.5s
- tests/test_function_length.py      ~?s (scans all .py)

## Strategy
1. Parallelize with pytest-xdist (`pip install pytest-xdist`): `pytest -n auto`.
   Most tests are independent; a few touch the shared registry/kernel_db and
   must stay serial (mark with `@pytest.mark.serial`).
2. Cache the expensive corpus reads: `kernel_db.json` and the shipped manifest
   are re-parsed per test; load once in a session-scoped fixture.
3. Gate-clean tests (`TestEveryDeckRowIsGenerative`) re-run `validate_config`
   per (family, pattern, row); memoize by (family, pattern, frozen knobs).
4. `test_function_length.py` re-walks the tree; restrict to changed files via
   `--lf`/`--nf` in local runs.
5. Split the overnight-focused subset (already in command.txt) from the full
   suite so preflight stays < 90s.

## Status
- pytest-xdist not yet installed (requirements.txt). Add when the parallel run
  is wired into command.txt.
