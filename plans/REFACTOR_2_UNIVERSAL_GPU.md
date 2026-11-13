# Refactor 2 — Universal GPU (arch-independent oto): commit tasklist

**Status:** IMPLEMENTATION PLAN. Execute commit-by-commit. Gate: full preflight green after every commit. No regressions.

**Companion:** REFACTOR_1 (oto/ package) — DONE. Assumes `oto/` layout + `oto/device/` seam exist.

---

## Phase 0 — Finish Refactor 1 (verify baseline)

- **C0.1** Run full preflight (`pytest -m preflight`). Record baseline: 175 passed, 2 pre-existing resolve_cells failures. Save as regression floor. Gate: no new failures.

## Phase 1 — DeviceProfile dataclass + gfx90c extraction

- **C1.1** Create `oto/device/profile.py`: frozen `DeviceProfile` dataclass (codename, isa, num_cus, simds_per_cu, lanes_per_simd, max_waves_per_cu, max_clock_mhz, lds_per_cu_kb, l2_size_kb, vgpr_per_cu, has_mfma, has_dp4a, has_packed_bf16, global_load_byte_cap, peak_gflops, family_shapes, realistic_ceilings, family_dtype_char, family_dtypes, family_bytes_per_element, assembly_gates, theoretical). Nested frozen `AssemblyGatePolicy`, `TheoreticalLimits`. Gate: import + dataclass construction test.
- **C1.2** Create `profiles/gfx90c.json`: mechanical extraction of current constants from `oto/device/peaks.py` (PEAK_GFLOPS, FAMILY_SHAPES, FAMILY_DTYPE_CHAR, FAMILY_DTYPES, FAMILY_BYTES_PER_ELEMENT, REALISTIC_CEILINGS, NUM_CUS=7, clock=1800, LDS=64KB, VGPR=65536, has_mfma=False, has_dp4a=False). Gate: `json.load` + equals hand-derived expected.
- **C1.3** `oto/device/loader.py`: `load_profile(codename)` reads `profiles/<codename>.json` → `DeviceProfile`. `load_profile_from_starter(path)` for new devices. Gate: load gfx90c → equals C1.2 constants.
- **C1.4** `oto/device/__init__.py`: export `load_profile`, `DeviceProfile`. Update `peaks.py` docstring: "constants live in profiles/ now; peaks.py is the gfx90c re-export shim for compat". Gate: existing imports unchanged.
- **C1.5** Add `tests/test_profile.py`: assert gfx90c profile reproduces every current constant in `oto/device/peaks.py` exactly (PEAK_GFLOPS, FAMILY_SHAPES, etc.). Gate: green.

## Phase 2 — Route consumers through profile (remove literals)

Order: gates first (most isolated), then analytics/report, then harness.

- **C2.1** `oto/tensile/gates/vgpr_model.py`: replace module-level constants (GLOBAL_LOAD_BYTE_CAP, FAMILY_BYTES_PER_ELEMENT, VGPR_PER_CU, ACCVGPR_BUDGET, LDS_BUDGET, BYTES_PER_ELEMENT, MAX_LDS_BYTES) with profile-derived. Keep as module globals populated from default profile (gfx90c) for backward compat, but functions take `profile` param. Gate: test_vgpr_model passes.
- **C2.2** `oto/tensile/gates/assembly.py`: `assembly_class_valid` takes `profile`; gfx90c rules become `AssemblyGatePolicy` predicates parameterised by `has_mfma`/dtype. Gate: test_assembly passes.
- **C2.3** `oto/tensile/gates/loads.py`: load cap from `profile.global_load_byte_cap`. Gate: test_loads passes.
- **C2.4** `oto/tensile/gates/occupancy.py`: `ldspad_feasible`, `occupancy_feasible` take profile. Gate: test_occupancy passes.
- **C2.5** `oto/metrics/analytics.py`, `report.py`, `ab_delta.py`, `cell_status.py`, `family_attribution.py`: read ceilings/peaks from profile instead of peaks module globals. Gate: test_analytics, test_report, test_ab_audit pass.
- **C2.6** `oto/harness/*.py` (kernel_db, generate_candidates, coverage_map, corpus_census, occupancy_audit, asm_occupancy, resolve_cells): take profile for family shapes/ceilings. Gate: harness tests pass.
- **C2.7** `oto/tensile/config_writer.py`, `candidate.py`, `candidate_emission.py`, `knob_sweep.py`, `legality.py`, `best_library.py`: route through profile. Gate: tensile tests pass.
- **C2.8** `oto/runners/*.py` (driver, benchmark, reporting, synthesis, clocks): route through profile; remove `gfx90c_common` imports. Gate: runner tests pass.
- **C2.9** `oto/checks/*.py`, `oto/tools/*.py`: route through profile. Gate: checks pass.
- **C2.10** Delete `gfx90c_common.py` (if still exists at root). Move resolvers to `oto/device/resolvers.py` (kernel_typecode, family_from_kernel_name, cell_key, cube_side, shipped_cells, shipped_cell_set, kernel_key — currently in peaks.py). Gate: `grep -rn "gfx90c_common" oto/` empty; full preflight green.

## Phase 3 — Universalize port_tensile.py

- **C3.1** Auto-detect codename: read GPU codename from `rocminfo` (or `--codename`). Resolve profile via `load_profile`. Gate: unit test with mocked rocminfo.
- **C3.2** Validate detected HW vs profile (num_cus, clock, ISA); warn on mismatch. Gate: test.
- **C3.3** Parameterise spoof reference by `profile.spoof_reference` (gfx90c=gfx900; others=none → native-only path). Gate: test with synthetic profile.
- **C3.4** Remove `--arch` flag; use profile. Gate: cli test.
- **C3.5** End-to-end: gfx90c run behaves identically (golden-file comparison of deck + report). Gate: regression test.

## Phase 4 — Two-agent docs

- **C4.1** `oto/agents/theoretical_limits.py` (agent-1): reads starter file + API key, researches first-party specs, derives ALU peaks, writes `<codename>_theoretical_limits.md` with §0-§7 structure, emits profile JSON. Gate: generates gfx90c doc matching current hand-written one (diff < 5%).
- **C4.2** `oto/agents/tuning_context.py` (agent-2): reads theoretical-limits + starter, writes `<codename>_tuning_context.md`. Gate: structure match.
- **C4.3** API key handling: read from starter YAML block or env var; never persisted. Gate: test no key on disk.
- **C4.4** Wire agents into meta-agent orchestrator. Gate: end-to-end gfx90c doc gen.

## Phase 5 — Automated potential_configs.md

- **C5.1** `oto/tools/potential_configs_gen.py`: reads run outputs (kernel_db + ledger) + agent research, synthesises potential_configs.md sections (verdict anatomy, occupancy audit, ranked plan). Gate: generates gfx90c potential_configs matching current structure.
- **C5.2** Meta-agent orchestrates: agents → workflow → potential_configs gen. Gate: full pipeline on gfx90c.

## Phase 6 — Generalise tests

- **C6.1** `tests/conftest.py`: profile fixture loads `profiles/gfx90c.json` as default. Gate: fixture works.
- **C6.2** Parameterise gate tests (test_occupancy_gate, test_legality_prior, test_cell_attribution) against `DeviceProfile`. Gate: green.
- **C6.3** Synthetic second profile (gfx906 or gfx900) + run gate tests against it. Gate: profile-specific outcomes asserted.
- **C6.4** Full suite: gfx90c parity (675 tests unchanged). Gate: green.

## Phase 7 — Second device validation

- **C7.1** Add `profiles/gfx900.json` (or gfx906) starter + profile. Run full workflow. Gate: produces library + report.
- **C7.2** `grep -rnE "gfx90c|5650U|1800|NUM_CUS = 7" oto/` → only `oto/device/` + `profiles/`. Gate: empty elsewhere.

## Phase 8 — Acceptance criteria verification

- **C8.1** Run full preflight + functional tests. Gate: green.
- **C8.2** Verify no device literals in code (grep). Gate: pass.
- **C8.3** Auto-detect test on gfx90c. Gate: pass.
- **C8.4** Starter-driven: add a synthetic device with zero code changes. Gate: pass.

---

## Commit discipline

Every commit: (1) single concern, (2) preflight green, (3) no new pyflakes, no new ruff findings and every tracked file byte-compiles (`tests/test_pyflakes.py` / `tests/test_ruff.py` / `tests/test_py_compile.py`), (4) no function >60 lines, (5) commit message references phase/commit ID (e.g., "R2-C1.3: profile loader").

## Risk: large refactor. Mitigation: each phase independently shippable; Phase 1-2 keep gfx90c behaviour identical (profile reproduces constants exactly → tests unchanged).

## Open questions for user

1. Which second device for validation? (gfx900 / gfx906 / gfx90a)
2. API key provider for agents (OpenAI / Anthropic / local)?
3. Starter file format preference (Markdown+YAML block vs pure JSON)?
EOF
echo "written"