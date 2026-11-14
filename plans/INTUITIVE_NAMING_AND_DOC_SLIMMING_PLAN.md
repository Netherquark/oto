# Intuitive Naming & Documentation Slimming — Plan

Status: **PROPOSAL — not executed.** No file renames, no doc deletions, no
docstring edits land until this plan is approved and each step below is
executed as its own verified batch.

Scope: the whole tracked repository. Goal: a developer who has never seen
this codebase can infer what every file does from its path alone, and can
read any document in the tree without tripping over ephemeral scratch —
task lists, session hashes, refactor-plan archaeology — that no longer
describes anything that exists.

Two hard constraints override everything else:

1. **Functionality is untouched.** A rename is `git mv` plus every reference
   updated; behaviour does not change. Verifier/CI/guard updates are part of
   the rename batch, never an afterthought.
2. **Ephemera is deleted, not moved.** A one-shot plan that has served its
   purpose is deleted from the tree. Durable facts it captured are folded
   into the owning document first. "Park it in a folder" is how a repo rots
   into a scratch pile.

## §0. How to read this plan

Every tracked file appears in exactly one of four actions:

| Action | Meaning |
|---|---|
| **KEEP** | no rename, no content change (or trivial ref-fixups only) |
| **RENAME** | `git mv` + global reference update |
| **REWRITE** | content rewrite in place (or move + rewrite first) |
| **DELETE** | removed; durable facts folded into a KEEP file first |

Nothing here invents new functionality, new tests or new APIs. This is a
presentation pass with a large blast radius, executed in small batches
(procedure in §10).

## §1. Repository inventory (baseline)

298 tracked files:

| Area | Files | Handled in |
|---|---|---|
| `oto/` package | 162 | §2 |
| `tests/` | 80 | §3 |
| root `*.md` | 19 | §4 |
| `docs/*.md` | 14 | §5 |
| `docs/*.json` | 3 | §5, §8 |
| `docs/skills/*.md` | 2 | §5 |
| `plans/*.md` | 6 | §6 |
| `archive/*.md` | 4 | §7 |
| data/config/bin (`phases.yaml`, `profiles/`, `ruff.toml`, `pytest.ini`, `bin/oto`, root `.json`, `LICENSE`, `.gitignore`, `gfx90c_vs_spoof.png`) | keep | §8 |

External contract notes:

- `test_file_length.py` ratchets files over 600 lines; renames must not push
  a grandfathered file over, and no KEEP decision may add new offenders.
- `test_function_length.py` caps functions at 60 lines.
- `oto/tools/verifiers/verify_symbols.py` carries the `RENAMES` table; every
  module rename MUST add an entry (this is how the verifier follows renames).
- `oto/README.md` is generated from module docstrings; regenerate after each
  rename batch (`python3 -m oto.inventory`).
- `docs/cli.md` is generated from the parser; regenerate after command-tree
  edits only (`oto help --write docs/cli.md`).
- The docs registry (`docs/README.md`) is enforced by `test_docs_registry.py`;
  every deleted/moved doc must be updated there.

---

## §2. `oto/` module renames

Package names stay as they are (§2.16); the rename budget is spent on
modules. Recently renamed modules (Phase A/B/C of the earlier cleanup) are
KEEP unless incoherent — re-renaming churns references for zero legibility.

### §2.1 `oto/` root

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | public API; renaming breaks `import oto` |
| `__main__.py` | KEEP | — | `python -m oto`; conventional |
| `version.py` | KEEP | — | obvious |
| `docs_index.py` | RENAME | `docs_index_writer.py` | collides visually with `docs/docs_index.json`; this *writes* it |
| `inventory.py` | RENAME | `readme_gen.py` | "inventory" reads like a census; the module regenerates `oto/README.md` |
| `yamlio.py` | RENAME | `yaml_cached.py` | the load-side content cache is the point, not "yaml I/O" |

### §2.2 `oto/agents/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `agent_tools.py` | KEEP | — | recently renamed; clear |
| `orchestrator.py` | RENAME | `meta_agent.py` | the module's own docstring: "Meta-agent: orchestrates agent-1 -> agent-2 -> potential_configs" |
| `research.py` | RENAME | `research_client.py` | a callable factory, not a corpus of research |
| `theoretical_limits.py` | KEEP | — | |
| `tuning_context.py` | KEEP | — | |

### §2.3 `oto/checks/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `deck_legality.py` | KEEP | — | |
| `library_parity.py` | KEEP | — | |
| `registry_audit.py` | KEEP | — | |
| `retirement.py` | RENAME | `stability_retirement.py` | bare "retirement" reads like HR; this retires *stable* cells |
| `tensile_build.py` | KEEP | — | |
| `tensile_build_probe.py` | KEEP | — | |

### §2.4 `oto/cli/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `commands.py` | KEEP | — | |
| `dispatch.py` | KEEP | — | |
| `docs.py` | RENAME | `help_command.py` | bare `docs` reads as project documentation; this builds `oto help` |
| `doctor.py` | KEEP | — | |
| `errors.py` | KEEP | — | |
| `global_flags.py` | KEEP | — | |
| `output.py` | KEEP | — | |
| `parser.py` | KEEP | — | |

### §2.5 `oto/device/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `derive.py` | RENAME | `derive_limits.py` | bare `derive` names nothing; it derives the theoretical-limits table |
| `detect.py` | RENAME | `device_detect.py` | "detect" inside `oto.device` still needs the object |
| `loader.py` | KEEP | — | |
| `profile.py` | KEEP | — | |
| `tensile_isa.py` | KEEP | — | the Tensile `CurrentISA` triple table; unambiguous |
| `vocabulary.py` | RENAME | `kernel_vocabulary.py` | unqualified `vocabulary`; the content is the kernel-name vocabulary |

### §2.6 `oto/harness/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `asm_occupancy.py` | KEEP | — | |
| `candidate_overlay.py` | KEEP | — | |
| `candidate_pool.py` | KEEP | — | |
| `candidate_rows.py` | KEEP | — | recently renamed |
| `cell_knob_diff.py` | KEEP | — | |
| `corpus_census.py` | KEEP | — | |
| `coverage_graph.py` | KEEP | — | |
| `coverage_map.py` | KEEP | — | |
| `deck_probe.py` | KEEP | — | |
| `failure_triage.py` | KEEP | — | |
| `gate_calibration.py` | KEEP | — | |
| `generate_candidates.py` | RENAME | `candidate_generator.py` | `generate_*` verb ordering breaks the noun-convention of siblings |
| `kernel_db.py` | KEEP | — | |
| `measure_vgprs.py` | RENAME | `vgpr_measurement.py` | verb phrase; the module is the measurement model + CLI |
| `occupancy_bounds.py` | KEEP | — | |
| `regression_matrix.py` | KEEP | — | |
| `resolve_cells.py` | RENAME | `cell_resolver.py` | verb phrase; sibling modules are nouns |
| `rows_frontier.py` | KEEP | — | |
| `rows_ladders.py` | KEEP | — | |
| `rows_smallcells.py` | KEEP | — | |
| `rule_calibration.py` | KEEP | — | |
| `tensile_probe.py` | KEEP | — | |
| `visual_check.py` | KEEP | — | |

### §2.7 `oto/ledger/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `agent_coverage.py` | KEEP | — | |
| `agent_mutate.py` | RENAME | `agent_mutation.py` | verb phrase; siblings are nouns |
| `agent.py` | RENAME | `convergence_agent.py` | `agent.py` says nothing; the class is `ConvergenceAgent` |
| `harvest.py` | KEEP | — | |
| `mutator.py` | KEEP | — | the class is `Mutator` |
| `mutator_outcomes.py` | KEEP | — | |
| `registry.py` | KEEP | — | `SQLiteRegistry` composition root |
| `registry_core.py` | KEEP | — | recently renamed neighbour class convention |
| `registry_proposals.py` | KEEP | — | recently renamed |
| `registry_queries.py` | KEEP | — | recently renamed |

### §2.8 `oto/metrics/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `ab_audit.py` | KEEP | — | `ab_` prefix is the established A/B-arm vocabulary (native vs floor) |
| `ab_band.py` | KEEP | — | |
| `ab_delta.py` | KEEP | — | |
| `ab_identity.py` | KEEP | — | |
| `ab_records.py` | KEEP | — | |
| `analytics.py` | RENAME | `benchmark_analytics.py` | bare `analytics` describes nothing; it is CSV loading + per-cell aggregation |
| `build_status.py` | KEEP | — | recently renamed |
| `cell_policy.py` | KEEP | — | |
| `cell_status.py` | KEEP | — | |
| `coverage.py` | RENAME | `cell_coverage.py` | bare `coverage` reads like code coverage; this is cell evidence/fitness |
| `family_attribution.py` | KEEP | — | |
| `ledger_state.py` | KEEP | — | |
| `protocol.py` | RENAME | `measurement_protocol.py` | unqualified `protocol`; it is the like-for-like measurement-form classifier |
| `read_thermals.py` | RENAME | `thermal_telemetry.py` | `read_*` verb phrase; siblings are nouns |
| `render_status.py` | KEEP | — | |
| `report_coverage.py` | KEEP | — | |
| `report_css.py` | KEEP | — | |
| `report.py` | RENAME | `acceptance_report.py` | bare `report` is the thing every sub-report is about; it is the acceptance verdict report |
| `report_html.py` | KEEP | — | |
| `report_js.py` | KEEP | — | |
| `report_models.py` | KEEP | — | |
| `report_sections.py` | KEEP | — | |
| `run_plan.py` | KEEP | — | |
| `run_status.py` | KEEP | — | |
| `status_common.py` | RENAME | `status_helpers.py` | `common` is a junk drawer word; the module is exactly four helpers |
| `telemetry.py` | KEEP | — | |

### §2.9 `oto/runners/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `auto_prompt.py` | KEEP | — | |
| `auto.py` | RENAME | `convergence_loop.py` | the `--auto` flag drives the convergence loop; `auto.py` says nothing |
| `benchmark.py` | KEEP | — | unambiguous in this repo |
| `clocks.py` | RENAME | `clock_telemetry.py` | bare `clocks`; the module is clock coverage/RUL tracking |
| `corpus_loaders.py` | KEEP | — | |
| `driver.py` | KEEP | — | `TensileDriver` |
| `library_build.py` | KEEP | — | |
| `paths.py` | RENAME | `result_paths.py` | unqualified `paths`; the module resolves `gfx90c_results/` layout |
| `phases.py` | RENAME | `phase_runner.py` | `phases` reads like the calendar; it is the per-phase execution policy |
| `reference_floor.py` | KEEP | — | recently renamed |
| `reporting.py` | RENAME | `acceptance_reporting.py` | the docstring opens "The acceptance report"; `reporting` is bare |
| `stage_cli.py` | KEEP | — | |
| `stage_flags.py` | KEEP | — | |
| `timing.py` | KEEP | — | |
| `toolchain.py` | KEEP | — | |

### §2.10 `oto/tensile/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `best_library.py` | RENAME | `best_effort_library.py` | the CLI is `oto library best-effort`; the module writes the best-effort dat |
| `candidate_config.py` | KEEP | — | |
| `candidate_emission.py` | KEEP | — | |
| `candidate.py` | KEEP | — | |
| `config_writer.py` | KEEP | — | |
| `decks.py` | RENAME | `family_decks.py` | bare `decks`; the module holds the per-family candidate decks |
| `legality.py` | KEEP | — | |
| `knob_surface.py` | KEEP | — | |
| `knob_sweep.py` | KEEP | — | |
| `library_parity.py` | KEEP | — | |
| `patterns.py` | RENAME | `contraction_patterns.py` | bare `patterns`; the content is the four contraction-pattern spellings |
| `shape_order.py` | KEEP | — | |
| `shipped_library.py` | RENAME | `shipped_floor.py` | "shipped floor" is the project's own term for the gfx900 reference floor |
| `shipped_manifest.py` | RENAME | `shipped_floor_manifest.py` | sibling of `shipped_floor`; both start with the same prefix after the rename |

### §2.11 `oto/tensile/gates/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `assembly.py` | KEEP | — | |
| `gate_common.py` | KEEP | — | recently renamed; "primitives" vs "common" is cosmetic and not worth churn |
| `ldspad.py` | KEEP | — | |
| `loads.py` | KEEP | — | |
| `memo.py` | KEEP | — | |
| `occupancy.py` | KEEP | — | |
| `vgpr_model.py` | KEEP | — | the VGPR/LDS/ISA cost model; unambiguous |

### §2.12 `oto/tensile/synthesis/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `donor_knobs.py` | KEEP | — | recently renamed |
| `donor_mutator.py` | KEEP | — | |
| `donor_patterns.py` | KEEP | — | |
| `manifest.py` | RENAME | `pipeline_manifest.py` | unqualified `manifest`; this is the synthesis pipeline's aggregate manifest, not the shipped-floor one |
| `tile_space.py` | KEEP | — | |

### §2.13 `oto/tools/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `all_runs.py` | RENAME | `run_census.py` | "AllRuns" reads like a command name; the module builds the run census |
| `chart.py` | RENAME | `benchmark_chart.py` | bare `chart`; one chart exists (native vs floor), this renders it |
| `consolidate.py` | KEEP | — | the family name is documented; see §10 sweep instead of rename churn |
| `consolidate_deck.py` | KEEP | — | ditto |
| `consolidate_floor.py` | KEEP | — | ditto |
| `consolidate_install.py` | KEEP | — | ditto |
| `consolidate_targets.py` | KEEP | — | ditto |
| `corpus_audit.py` | KEEP | — | |
| `deck_review.py` | KEEP | — | |
| `potential_configs.py` | KEEP | — | the module *is* the potential-configs writer |

### §2.14 `oto/tools/verifiers/`

| File | Action | New name | Why |
|---|---|---|---|
| `__init__.py` | KEEP | — | |
| `ref_worktree.py` | KEEP | — | recently renamed |
| `verdict_corpus.py` | KEEP | — | |
| `verify_all.py` | KEEP | — | |
| `verify_config_render.py` | KEEP | — | recently renamed |
| `verify_gates.py` | KEEP | — | |
| `verify_methods.py` | KEEP | — | |
| `verify_report_render.py` | KEEP | — | |
| `verify_symbols.py` | KEEP | — | |

### §2.15 Summary of module renames

Renames proposed: **34**. KEEP: **128**. Package-level renames (e.g. `oto.harness` → something) were evaluated and rejected: §2.16.

### §2.16 Package-level names — evaluated, rejected

| Package | Verdict | Reason |
|---|---|---|
| `oto.harness` | KEEP | Renaming to `oto.analysis` / `oto.bench` / `oto.measurement` would churn every doc, test and script reference for roughly zero legibility gain; the module docstrings inside already explain it is the measurement/analysis harness. Acceptable. |
| `oto.checks` | KEEP | "checks" is conventional CLI vocabulary (`oto check …`); the modules inside carry the specifics (`deck_legality`, `registry_audit`). |
| `oto.tools` | KEEP | "offline corpus tools"; renaming would collide with the standard library `tools` mental model anyway. |
| `oto.metrics` | KEEP | conventional; module names carry the specificity. |
| `oto.runners` | KEEP | execution-layer convention (driver, phases, toolchain). |
| `oto.ledger` | KEEP | durable-state layer; module names carry the specificity. |
| `oto.agents` | KEEP | agentic-consult layer. |
| `oto.tensile` | KEEP | the Tensile-facing layer; renaming breaks `oto tensile …` CLI intuition. |
| `oto.device` | KEEP | hardware-facts layer. |
| `oto.cli` | KEEP | CLI entry layer. |


## §3. `tests/` renames

`tests/` is the suite a new developer reads first; test names must say what
behaviour they pin. Fixtures/support modules already use `support_*` after the
Phase C cleanup.

| File | Action | New name | Why |
|---|---|---|---|
| `conftest.py` | KEEP | — | pytest convention |
| `support_convergence.py` | KEEP | — | recently renamed |
| `support_occupancy_gate.py` | KEEP | — | |
| `support_run_status.py` | KEEP | — | |
| `test_ab_audit.py` | KEEP | — | |
| `test_agents.py` | KEEP | — | |
| `test_asm_occupancy.py` | KEEP | — | |
| `test_auto_prompt.py` | KEEP | — | |
| `test_auto_reference_floor.py` | RENAME | `test_reference_floor.py` | `auto_reference_floor` no longer describes the subject; it pins the reference floor |
| `test_best_library.py` | RENAME | `test_best_effort_library.py` | module renamed to `best_effort_library.py` (§2.10) |
| `test_cell_attribution.py` | KEEP | — | |
| `test_cli_smoke.py` | KEEP | — | |
| `test_comparability.py` | KEEP | — | |
| `test_complex_flop_accounting.py` | KEEP | — | |
| `test_consolidate.py` | KEEP | — | |
| `test_corpus_census.py` | KEEP | — | |
| `test_coverage_cells.py` | KEEP | — | |
| `test_coverage_graph.py` | KEEP | — | |
| `test_db_mutator.py` | RENAME | `test_donor_mutator.py` | module renamed in Phase A; test docstring still says DBMutator (kept as class name) |
| `test_deck_review.py` | KEEP | — | |
| `test_derive.py` | RENAME | `test_derive_limits.py` | module renamed to `derive_limits.py` (§2.5) |
| `test_docs_cli.py` | KEEP | — | |
| `test_docs_index.py` | KEEP | — | |
| `test_docs_registry.py` | KEEP | — | |
| `test_element_assertions.py` | KEEP | — | |
| `test_explicit_profile_threading.py` | KEEP | — | |
| `test_failure_triage.py` | KEEP | — | |
| `test_file_length.py` | KEEP | — | |
| `test_function_length.py` | KEEP | — | |
| `test_gate_calibration.py` | KEEP | — | |
| `test_generate_candidates.py` | RENAME | `test_candidate_generator.py` | module renamed to `candidate_generator.py` (§2.6) |
| `test_harness_tools.py` | RENAME | `test_agent_tools.py` | module renamed to `agent_tools.py` (Phase A); test name still echoes the old one |
| `test_interactive_keys.py` | KEEP | — | |
| `test_knob_sweep.py` | KEEP | — | |
| `test_ledger_durability.py` | KEEP | — | |
| `test_legality_prior.py` | RENAME | `test_legality.py` | `_prior` is leftover from an abandoned "legality prior" framing |
| `test_legal_slow.py` | RENAME | `test_legal_slow_paths.py` | `legal_slow` reads like a property; the suite covers the deliberately-illegal slow paths |
| `test_library_parity.py` | KEEP | — | |
| `test_measurement_integrity.py` | KEEP | — | |
| `test_mutation_arm.py` | KEEP | — | |
| `test_mutator.py` | KEEP | — | |
| `test_occupancy_live_deck.py` | KEEP | — | |
| `test_occupancy_model_lds.py` | KEEP | — | |
| `test_occupancy_model_vgpr.py` | KEEP | — | |
| `test_outcome_writeback.py` | KEEP | — | recently renamed |
| `test_overlay_merge.py` | KEEP | — | recently renamed |
| `test_parent_selection.py` | KEEP | — | |
| `test_paths.py` | RENAME | `test_result_paths.py` | module renamed to `result_paths.py` (§2.9) |
| `test_profile.py` | KEEP | — | |
| `test_profile_gates.py` | KEEP | — | |
| `test_profile_second_device.py` | KEEP | — | |
| `test_proposal_durability.py` | KEEP | — | |
| `test_proposals_ledger.py` | KEEP | — | |
| `test_protocol.py` | RENAME | `test_measurement_protocol.py` | module renamed to `measurement_protocol.py` (§2.8) |
| `test_py_compile.py` | KEEP | — | |
| `test_pyflakes.py` | KEEP | — | |
| `test_readonly_reporting.py` | KEEP | — | recently renamed |
| `test_reference_tiers.py` | KEEP | — | |
| `test_registry_kernel_db_auto.py` | RENAME | `test_auto_reference_registry.py` | `registry_kernel_db_auto` is three jargon words; it pins the reference-registry path for the `--auto` loop |
| `test_report_coverage.py` | KEEP | — | |
| `test_report_family_case.py` | KEEP | — | |
| `test_report_probe_glob.py` | KEEP | — | |
| `test_resolve_cells.py` | RENAME | `test_cell_resolver.py` | module renamed to `cell_resolver.py` (§2.6) |
| `test_ruff.py` | KEEP | — | |
| `test_rule_calibration.py` | KEEP | — | |
| `test_run_status_live.py` | KEEP | — | |
| `test_run_status_report.py` | KEEP | — | |
| `test_shape_order.py` | KEEP | — | |
| `test_starter_pair.py` | KEEP | — | |
| `test_synthesis_band_wiring.py` | KEEP | — | |
| `test_synthesis_sampler.py` | KEEP | — | |
| `test_synthesis_sweep.py` | KEEP | — | |
| `test_tensile_params.py` | KEEP | — | |
| `test_thermal_gate.py` | KEEP | — | |
| `test_tile_frontier.py` | KEEP | — | |
| `test_toolchain.py` | KEEP | — | |
| `test_toolchain_layout.py` | KEEP | — | |
| `test_verify_run.py` | RENAME | `test_corpus_audit.py` | module renamed to `corpus_audit.py` (Phase A); test name still references the old module |
| `test_visual_check.py` | KEEP | — | |
| `test_writer_forwards_sweep_knobs.py` | KEEP | — | |

Tests renamed: **13**. KEEP: **67**.

Every test rename is paired with the matching import-path update and, for
the four `test_generate_candidates`/`candidate_generator` pairings, the
`conftest.py` preflight list (if it names these modules) — check
`tests/conftest.py` for every renamed module path.

## §4. Root `*.md` — disposition

Root files a reader meets first. The durable research/contract/results docs
move into `docs/` (one home, one registry); the session scratch deletes.

| File | Action | Destination | Why |
|---|---|---|---|
| `README.md` | KEEP | — | repo orientation; ref-fixups only |
| `claude.md` | KEEP | — | the Class-A entry contract; ref-fixups only |
| `changelog.md` | KEEP | — | append-only evolution log; never rewritten |
| `incomplete_work.md` | KEEP | — | the open-work register |
| `docs/shipped_floor_contract.md` | MOVE + RENAME | `docs/shipped_floor_contract.md` | it *is* the replication contract doc; root is the wrong shelf and the name says nothing |
| `docs/knowledge_base.md` | MOVE | `docs/docs/knowledge_base.md` | the WHAT-layer architecture doc belongs with the other docs |
| `docs/results.md` | MOVE | `docs/docs/results.md` | measured evidence belongs in docs/ |
| `docs/gfx90c_theoretical_limits.md` | MOVE | `docs/docs/gfx90c_theoretical_limits.md` | device-limits authority |
| `docs/gfx90c_tuning_guide.md` | MOVE | `docs/docs/gfx90c_tuning_guide.md` | tuning cookbook |
| `docs/research/kernel_tuning.md` | MOVE + RENAME | `docs/research/kernel_tuning.md` | research layer, different audience than the cookbooks |
| `docs/research/complex_gemm_brief.md` | MOVE + RENAME | `docs/research/complex_gemm_brief.md` | ditto |
| `docs/potential_configs.md` | MOVE | `docs/docs/potential_configs.md` | name is accurate; belongs in docs/ |
| `docs/search_philosophy.md` | MOVE + RENAME | `docs/search_philosophy.md` | "tensile tuning context" is opaque; it owns the objective/gates/search-order philosophy |
| `docs/audit_register.md` | MOVE | `docs/audit_register.md` | rename drops the agent-persona framing; it is the audit-findings register |
| `implementation_plan.md` | DELETE | — | "APPROVED-IN-PRINCIPLE" session artifact; the stage detail lives in `changelog.md`, the durable cookbook content folds into `docs/docs/gfx90c_tuning_guide.md` (the ceiling/floor gates and the acceptance bar) before deletion |
| `context.md` | DELETE | — | 2026-10-15 sandbox research copy; header says it was never verified against the local machine, cites `/mnt/user-data/outputs/` paths, and duplicates `plans/REFACTOR_2_UNIVERSAL_GPU.md` + `changelog.md` |
| `context_raw.md` | DELETE | — | same artifact, more of it; explicitly marked UNVERIFIED and "not at this path" |
| `archive/prior_insights.md` | MOVE | `archive/prior_insights.md` | frozen prior-campaign autopsy; it is evidence, not a living doc |
| `archive/prior_research_archive.md` | MOVE | `archive/prior_research_archive.md` | ditto |

Moved files must be added to `docs/README.md` (registry) with a stable `Class`
and the registry generator must still pass `test_docs_registry.py`. Every
reference to a moved/renamed root doc across the tree is updated in the same
commit (see §10.3). `changelog.md` is the one exception to the rewrite rule:
it is append-only and its historical paths stay as they are.

## §5. `docs/` — disposition

| File | Action | Why |
|---|---|---|
| `README.md` | REWRITE (content + registry sync) | registry must reflect §4 moves and §6 deletions; stale rows (`plans/*.md`, root moves) are removed |
| `cli.md` | KEEP | generated by `oto help --write` |
| `comparability.md` | KEEP + ref-fixups | like-for-like rule; references must point at moved files |
| `design_language.md` | KEEP | HTML report design spec |
| `docstrings.md` | KEEP | the docstring convention |
| `harness_runbook.md` | KEEP + ref-fixups | harness guardrails |
| `agent_reference.md` | KEEP + ref-fixups | harness quick reference |
| `operator_campaign.md` | KEEP | operator tuning campaign (needs no rename) |
| `operator_runbook.md` | KEEP | Class-B entry |
| `starter_pair.md` | KEEP | |
| `starter_template.md` | KEEP | |
| `starter_template.json` | KEEP | |
| `gfx902_starter.md` | KEEP | |
| `gfx902_starter.json` | KEEP | |
| `docs_index.json` | KEEP | generated by `oto/docs_index.py` |
| `skills/class_a_developer.md` | KEEP | referenced by claude.md guardrails |
| `skills/class_b_operator.md` | KEEP | ditto |
| `research/` (new) | NEW directory | holds `kernel_tuning.md`, `complex_gemm_brief.md` from §4 |

Docstring cleanup obligations (§9) sweep every doc above for: milestone
vocabulary ("Stage N", "Phase N"), session hashes, dates-as-authority,
references to deleted files (`implementation_plan.md`, `context*.md`,
`plans/*.md` after §6, `docs/shipped_floor_contract.md` old path), and odd self-references
(`oto/tools/verify_run.py` and friends).

## §6. `plans/` — all deleted after this plan lands

`plans/` exists because one-shot plans were parked in the tree. The user's
constraint is explicit: plans are ephemeral. Each of the six tracked plans is
a one-shot that has served its purpose (or is superseded by this plan). The
durable content is folded as noted; the registry rows are removed; `plans/`
is then empty and removed from the tracked tree.

| File | Action | Fold durability |
|---|---|---|
| `MASTER_PLAN.md` | DELETE | open items → `incomplete_work.md` (already deduped against each other; verify no open item is lost); verification commands and guardrails that outlive the session → `claude.md` |
| `RENAME_AND_DOC_CLEANUP_PLAN.md` | DELETE | superseded by this file; the residual decisions are either in this plan or in `changelog.md` |
| `CLI_UX_REWORK.md` | DELETE | CLI vocabulary already lives in `docs/cli.md` and `claude.md`; the rework landed |
| `REFACTOR_2_UNIVERSAL_GPU.md` | DELETE | device-independence record lives in `changelog.md`; backlog folded to `incomplete_work.md` |
| `AGENTIC_POTENTIAL_CONFIGS_PLAN.md` | DELETE | the agentic-consult design is superseded by the operator runbook's research flow; nothing implemented it, nothing needs it; the design is re-derivable from `docs/operator_runbook.md` + `docs/operator_campaign.md` |
| `test_optimization.md` | DELETE | suite optimisation landed; `changelog.md` holds the record |

This plan itself, `plans/INTUITIVE_NAMING_AND_DOC_SLIMMING_PLAN.md`, deletes
itself in its final batch (§10.6), after which `plans/` is gone.

## §7. `archive/` — disposition

| File | Action | Why |
|---|---|---|
| `archive/corpus.pass1_20261014.md` | KEEP | frozen prior-corpus evidence |
| `archive/corpus2.pass2_20261014.md` | KEEP | ditto |
| `archive/corpus3.pass3_20261014.md` | KEEP | ditto |
| `archive/RESEARCH_PROMPT3.pass3_20261014.md` | KEEP | ditto |
| `archive/prior_insights.md` (moved §4) | KEEP | frozen prior autopsy |
| `archive/prior_research_archive.md` (moved §4) | KEEP | frozen prior research |

The remaining 6.4 GB under `archive/` is untracked runtime output
(`archive/gfx90c_runs/`, etc.) and is outside this plan. The tracked files
above stay — they are the cited prior evidence, not scratch.

## §8. Data, config, bin

| File | Action | Why |
|---|---|---|
| `phases.yaml` | KEEP | the candidate deck |
| `profiles/gfx90c.json` | KEEP | device facts |
| `ruff.toml` | KEEP | guard config |
| `pytest.ini` | KEEP | guard config |
| `bin/oto` | KEEP | the PATH entry |
| `LICENSE` | KEEP | |
| `.gitignore` | KEEP | |
| `.env.example` | KEEP | |
| `gfx90c_vs_spoof.png` | RENAME | `docs/assets/native_vs_floor.png` | referenced by nothing tracked; moving under `docs/assets/` puts it with the docs that could use it — or DELETE if no doc wants it (decide in execution) |
| `docs/gfx902_starter.json`, `docs/starter_template.json` | KEEP | |
| `docs/shipped_floor_contract.md` (§4 moved) | n/a | see §4 |

## §9. The AI-slop / ephemera sweep (rewrites, not renames)

Deleting a file is not enough; the surviving text must stop referencing
things that do not exist. The sweep is a checklist applied to **every** doc
and docstring in the tree, plus the specific stale-reference classes below.

### §9.1 Vocabulary replacements (docstrings and docs)

| Pattern | Replacement rule |
|---|---|
| `Hplan.5`, `Option H Phase N`, `AC 1b`, `AC 4a` | delete, or restate as the user-visible contract (e.g. "no function over 60 lines") without the milestone tag |
| `Stage N` / `Phase N` in module docstrings | restate as the module's actual responsibility |
| dates used as authority ("2026-10-14 like-for-like regrade") | cite the owning doc (`docs/comparability.md`, `docs/docs/results.md`, `changelog.md`) or drop the date |
| commit hashes (e.g. `8438927`) in docstrings | drop; `git log` is the authority |
| `REFACTOR_2_UNIVERSAL_GPU.md`, `MASTER_PLAN.md`, `plans/…` references | point at `changelog.md` / `incomplete_work.md` / the owning doc instead |
| `verify_run.py`, `allruns.py`, `occupancy_audit.py`, `harness_tools.py`, `ldspad_gate.py`, `potential_configs_gen.py` | the prerenames; every occurrence means the author didn't grep after the Phase A renames — fix to current module names |
| `analytics_loaders.py`, `runners/cli.py`, `runners/flags.py`, `metrics/policy.py`, `tensile/library.py` | ditto — Phase A/B renames |
| `implementation_plan.md`, `context.md`, `context_raw.md` | deleted by §4; every reference must be removed or re-pointed |
| `plans/RENAME_AND_DOC_CLEANUP_PLAN.md`, `MASTER_PLAN.md`, `CLI_UX_REWORK.md`, `REFACTOR_2_UNIVERSAL_GPU.md`, `AGENTIC_POTENTIAL_CONFIGS_PLAN.md`, `test_optimization.md` | deleted by §6; every reference must be removed or re-pointed |
| `docs/shipped_floor_contract.md`, root paths of moved docs | re-point to `docs/…` |

### §9.2 Docs ownership check

For every doc, answer in one line: **who owns this fact now, and which file
does a reader go to?** If the answer is "the author's memory", the doc is
scratch and must either be rewritten to point at the owner or deleted.

### §9.3 Docstring hygiene gates

- No docstring mentions `gfx90c` as a *hardcoded current task*; device facts
  cite `oto.device.loader.current_profile()` or the profile.
- No docstring references a module by a name that does not exist in the same
  commit (grep-derived; CI-adjacent check, not a new test).
- `does not own` clauses name neighbours that exist.
- Milestone vocabulary count after the sweep: zero outside `changelog.md`.

### §9.4 Length/legibility check on kept docs

`README.md` (495 lines), `docs/README.md` (registry), `claude.md` (569),
`docs/operator_campaign.md` — after the reference fixes, each is re-checked
for internal contradictions (e.g. README §7 routing table references) and for
sections whose purpose is gone. No structural rewrite is planned beyond
reference fixes and the §6 removals; if a kept doc is found to be largely
untrue, that is a separate finding to file, not a silent rewrite.

## §10. Execution protocol (how the plan lands without breaking the build)

### §10.1 Order

1. **Docs moves first (§4).** Docs renames carry no code risk. Registry fixup
   in the same commit. Suite + verify-all green.
2. **Docs deletions (§6).** One commit per plan file; each folds its durable
   content first.
3. **Module renames, one package per commit (§2).**
4. **Test renames (§3).**
5. **§9 sweep.** Batches by package; docstring-only diffs.
6. **Self-deletion of this plan** and the empty `plans/` removal.

### §10.2 Per-commit protocol (every step, every time)

```
git add -A
python3 -m ruff check .            # or the focused OTO_GUARD_FILES=1 path
python3 -m pytest -q               # full suite; RC must be 0
python3 -m oto verify all          # ALL EQUIVALENCE CHECKS PASSED
```

Module-rename commits additionally:

```
RENAMES table in oto/tools/verifiers/verify_symbols.py extended
python3 -m oto.inventory           # oto/README.md regenerated
git commit                          # single-concern message: "rename: <package> ..."
```

### §10.3 Reference surgery

Every move/rename does a tree-wide grep for the old path **including**
`__pycache__`-adjacent sources, `.git` excluded, then:

```
grep -rl 'old/path' --include='*.py' --include='*.md' --include='*.json' --include='*.yaml' . | grep -v __pycache__ | xargs sed -i ...
```

…followed by a hand-check of every hit the `sed` missed (constructed paths,
interpolated strings, `sys.modules` aliases, docstrings with prose spellings).
Historical references in `changelog.md` stay; everything else must be current.

### §10.4 Verifier specifics

- `verify_symbols.py` → `RENAMES` gets one entry per module rename.
- `verify_methods.py` / `verify_gates.py` / `verify_config_render.py` /
  `verify_report_render.py` invoke the renamed modules by path only through
  `verify_all.py`, whose `CHECKS` list is already updated; no further edits.
- The `--base 2824c2f` run must still pass at the end (the recorded intentional
  divergence only).

### §10.5 Registry / index regeneration

After every batch: `oto/README.md` (`oto.inventory`), `docs/README.md`
(hand-updated, §5), `docs/docs_index.json` (`oto.docs_index`), `docs/cli.md`
(`oto help --write`) if the command tree changed.

### §10.6 Self-deletion

Final commit: `git rm plans/INTUITIVE_NAMING_AND_DOC_SLIMMING_PLAN.md`, empty
`plans/` removed, registry row removed. The plan's existence is recorded in
`changelog.md` as a one-line entry; the plan itself is not kept.

## §11. Risk register

| Risk | Mitigation |
|---|---|
| A grep miss leaves a stale reference in a rarely-imported path | the full suite + `oto verify all` after every commit; the `verify_*` checks catch path drift in the verifier chain itself |
| A test hardcodes a renamed path (as happened in this repo) | add `grep` for the old path across `tests/` in the batch; the four known hardcoded paths were all found and fixed that way |
| `oto/README.md` regen picks up unintended docstring drift | regen is deterministic; diff must be only the renamed modules |
| Renaming `acceptance_report.py` breaks `test_docs_cli.py` freshness | regenerate `docs/cli.md` whenever the parser changes; expected only in §2.9/§4 batches |
| `archive/` 6.4 GB blobs worry reviewers | explicitly out of scope; tracked set is 4 files + 2 moved prior docs |
| Doc deletion folds lose a durable fact | each §6 deletion lists its fold destination; the fold happens in the deletion commit, reviewed before the delete |
| The changelog becomes the only stale-reference survivor | allowed (append-only); all current docs must be current |
| Someone re-creates `plans/` | `.gitignore` does not block it; the registry test does not either — discipline + changelog note |

## §12. Acceptance criteria (definition of done)

1. `git ls-files | grep -cE '^(plans/|implementation_plan.md|context.*\.md|docs/shipped_floor_contract.md)$'` → **0**.
2. `find oto tests -name '*.py'` shows zero non-intuitive renames remaining: the rename table in §2/§3 is fully applied.
3. `python3 -m pytest -q` → RC=0, 1077+ tests passing.
4. `python3 -m oto verify all` → ALL EQUIVALENCE CHECKS PASSED.
5. `python3 -m oto verify all --base 2824c2f` → matches the drift manifest (no unmanifested divergence).
6. `docs/README.md` registry lists every tracked `.md` and nothing else; `test_docs_registry.py` green.
7. `docs/cli.md` byte-identical to `oto help --write docs/cli.md`; `test_docs_cli.py` green.
8. `grep -rniE 'Hplan|AC 1b|Option H Phase' --include='*.py' --include='*.md' . | grep -v changelog.md | grep -v __pycache__` → 0 hits.
9. Every moved doc's references tree-wide updated; spot-audit of 10 random cross-references passes.
10. `changelog.md` records the campaign in one entry; `incomplete_work.md` reflects only open items.

## §13. Open questions for the owner (blockers before execution)

1. **`gfx90c_vs_spoof.png`** — delete, or move to `docs/assets/native_vs_floor.png`?
2. **`docs/shipped_floor_contract.md` rename** — proposed `docs/shipped_floor_contract.md`; owner may prefer `docs/floor_contract.md`.
3. **`docs/search_philosophy.md` rename** — proposed `docs/search_philosophy.md`; owner may prefer keeping the name.
4. **Root `docs/results.md` / `docs/knowledge_base.md`** — confirmed OK to move under `docs/`, or must they stay at root?
5. **`prior_*` files** — confirmed OK to move to `archive/`?
6. **`plans/` total deletion** — confirm no plan file is to be retained in-tree.
7. **Module rename budget (30)** — confirm, or the owner wants a smaller/larger set.
