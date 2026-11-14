# The ``oto/`` package map

Generated. Regenerate with ``python3 -m oto._map``.

Each entry is the first sentence of that module's docstring, so the
only way to make this file stale is to delete the docstring. Line
counts are never quoted here -- they go wrong the day a file moves.

## oto/ -- the package root

* ``__main__.py`` — Entry point for ``python3 -m oto``.
* ``_version.py`` — Version string for the oto CLI.
* ``docs_index.py`` — Machine-readable docs ecosystem index for agentic routing.
* ``yamlio.py`` — The project's YAML reader: libyaml when it is there, cached by content.

## oto/device/ — hardware facts

* ``device/derive.py`` — Deterministic ALU-peak derivation for any ``DeviceProfile``.
* ``device/detect.py`` — Device auto-detection: resolve the GPU codename from the system.
* ``device/loader.py`` — Device profile loader — the frozen, in-memory view of one GPU.
* ``device/profile.py`` — Device profile: the frozen, in-memory view of one GPU.
* ``device/tensile_isa.py`` — Tensile ``CurrentISA`` version triples for the gfx9 family.
* ``device/vocabulary.py`` — Coverage-grid vocabulary: cell identity and kernel-name parsing.

## oto/tensile/ — the Tensile-facing candidate pipeline

* ``tensile/best_library.py`` — Best-effort device ``TensileLibrary.dat`` carved from the full kernel database.
* ``tensile/candidate.py`` — Candidate generation: the family deck, the sampler, and the append boundary.
* ``tensile/candidate_config.py`` — The candidate payload dataclass.
* ``tensile/candidate_emission.py`` — The append boundary: how a candidate becomes a launchable phase.
* ``tensile/config_writer.py`` — The launch-boundary config writer.
* ``tensile/decks.py`` — The curated family tile decks: the starting candidates, and what kind each is.
* ``tensile/knob_surface.py`` — The launch-boundary knob surface: what Tensile may and may not receive.
* ``tensile/knob_sweep.py`` — Emit the knob-sweep deck: every family's winner tile x one knob change.
* ``tensile/legality.py`` — The legality prior: manifest-derived legal domain, and source-cited walls.
* ``tensile/library.py`` — The shipped gfx900 manifest: pinning, identity, and the rerun tier triage.
* ``tensile/library_parity.py`` — The coverage-parity rule: what the produced TensileLibrary may address.
* ``tensile/patterns.py`` — The contraction-pattern vocabulary: one spelling, one meaning.
* ``tensile/shape_order.py`` — Canonical numeric ordering for Tensile problem-shape strings.
* ``tensile/shipped_library.py`` — The shipped gfx900 library: locating it, parsing it, rebuiling a kernel from its name.

### ``tensile/gates/``

* ``tensile/gates/assembly.py`` — The assembly-class gate: is this GEMM class legal on this device at all?
* ``tensile/gates/gate_common.py`` — Shared occupancy-gate vocabulary.
* ``tensile/gates/ldspad.py`` — The LDS-pad and swizzle group-C legality gate.
* ``tensile/gates/loads.py`` — Classic-path global-load divisibility, and the 16 B load-width cap.
* ``tensile/gates/memo.py`` — A content-keyed memo for the pure legality gates.
* ``tensile/gates/occupancy.py`` — Register-file and LDS occupancy gates.
* ``tensile/gates/vgpr_model.py`` — The measured VGPR model: tables and budgets the occupancy gate cites.

### ``tensile/synthesis/``

* ``tensile/synthesis/donor_mutator.py`` — DB-hooked candidate synthesis: wide + narrow + direction mutants.
* ``tensile/synthesis/donor_knobs.py`` — The forward-knob domains the DB-hooked mutator draws from.
* ``tensile/synthesis/donor_patterns.py`` — The per-family mutation patterns for the DB-hooked mutator.
* ``tensile/synthesis/manifest.py`` — Coverage-guided candidate synthesis for one cell.
* ``tensile/synthesis/tile_space.py`` — The one home for the tile and knob-group vocabulary the synthesisers share.

## oto/ledger/ — durable state + the mutation/convergence state machine

* ``ledger/agent.py`` — The convergence loop: harvest, mutate, decide, repeat.
* ``ledger/agent_coverage.py`` — Coverage guidance: what the ledger says about a cell, read once.
* ``ledger/agent_mutate.py`` — The mutation arm of the convergence loop.
* ``ledger/harvest.py`` — Parent selection: which candidate a cell's next mutation starts from.
* ``ledger/mutator.py`` — The ledger-backed mutation arm: sampling, emission, outcome write-back, overlay.
* ``ledger/mutator_outcomes.py`` — Candidate classification: what a measured candidate turned out to be.
* ``ledger/proposals.py`` — The Option-H proposal ledger: emitted candidates and their measured outcomes.
* ``ledger/queries.py`` — The registry's read side: records, phases and run lookups.
* ``ledger/registry.py`` — The ledger: append-only records, runs, phases and the Option-H proposals.
* ``ledger/registry_core.py`` — The ledger engine: connection, schema, transactions and run writes.

## oto/metrics/ — turning benchmark rows into verdicts, reports and status

* ``metrics/_status_common.py`` — Shared run-status helpers: timestamp parsing, duration formatting and the status/result -> display bucket mapping.
* ``metrics/ab_audit.py`` — Stage 7 acceptance A/B audit, and the CLI that prints it.
* ``metrics/ab_band.py`` — The acceptance band: how large a gap has to be before it is real.
* ``metrics/ab_delta.py`` — The native-vs-spoof A/B delta: the arithmetic every acceptance number rests on.
* ``metrics/ab_identity.py`` — A/B record identity: how the two arms are made comparable.
* ``metrics/ab_records.py`` — A/B record loading: the canonical (native, floor) inputs.
* ``metrics/analytics.py`` — Stage 5 analytics: CSV loading and per-cell aggregation.
* ``metrics/cell_status.py`` — Cell status: the RED / ORANGE / graded coverage classification.
* ``metrics/coverage.py`` — Coverage: cell evidence, cell states, and fitness for parent selection.
* ``metrics/family_attribution.py`` — Cell/family attribution: which family a measurement row belongs to.
* ``metrics/ledger_state.py`` — Ledger/corpus state for the status report: one read of the registry plus the reference corpus tally.
* ``metrics/policy.py`` — Cell policy: aggregation, the should_run gate, and retirement eligibility.
* ``metrics/protocol.py`` — Measurement-protocol classification: the like-for-like rule, in one place.
* ``metrics/read_thermals.py`` — The thermal envelope of one run, read from its telemetry CSV.
* ``metrics/render_status.py`` — The run-status text renderings and the live TTY panel.
* ``metrics/report.py`` — Stage 7 acceptance report: the verdict compute and the JSON writer.
* ``metrics/report_build.py`` — The status report builder: state assembly, ETA pricing and the report dict.
* ``metrics/report_css.py`` — The dashboard's static assets: CSS and the two inline scripts.
* ``metrics/report_figures.py`` — The acceptance report's problem-space coverage section.
* ``metrics/report_html.py`` — The acceptance dashboard renderer (JSON payload -> one HTML file).
* ``metrics/report_js.py`` — The dashboard report's inline JavaScript literals.
* ``metrics/report_models.py`` — The report's two payload dataclasses.
* ``metrics/report_sections.py`` — The dashboard's HTML section builders.
* ``metrics/run_plan.py`` — The run plan and the cost model that prices it.
* ``metrics/run_status.py`` — Run status: the report builder, the renderers and the live panel.
* ``metrics/telemetry.py`` — Telemetry: per-run CSV sampling of the GPU's clocks and power.

## oto/runners/ — execution

* ``runners/analytics_loaders.py`` — Corpus readers: how the driver loads measurements from every run.
* ``runners/auto.py`` — The ``--auto`` convergence loop: floor first, then tune to convergence.
* ``runners/auto_prompt.py`` — The five --auto questions, and the AutoPlan their answers bind.
* ``runners/benchmark.py`` — Phase execution: the one place a Tensile subprocess is launched.
* ``runners/cli.py`` — The argparse stage dispatch: the ``python3 -m oto`` command line.
* ``runners/clocks.py`` — Per-phase telemetry clocks and the thermal envelope around them.
* ``runners/driver.py`` — The driver composition root: identity, toolchain, and wiring.
* ``runners/flags.py`` — The driver's argparse flags, one helper per group.
* ``runners/paths.py`` — Shared path conventions for the driver.
* ``runners/phases.py`` — The phase runner: manifest merge, policy filter, identical-fp skip bypass.
* ``runners/reference.py`` — The gfx900 reference floor: build, resume, and recall.
* ``runners/reporting.py`` — The acceptance report: verdicts, arms, and the emitted JSON.
* ``runners/synthesis.py`` — Stage 6: emit the per-family library logic and build it with TensileCreateLibrary.
* ``runners/timing.py`` — The three numbers that get conflated as "runtime".
* ``runners/toolchain.py`` — Toolchain discovery: the Tensile checkout and the ROCm toolchain.

## oto/checks/ — operator diagnostics

* ``checks/deck_legality.py`` — Is this deck Tensile-legal? The four-gate preflight.
* ``checks/library_parity.py`` — The coverage-parity rule, as an executable check over an external deck.
* ``checks/registry_audit.py`` — Inspect the registry DB for label contamination ('auto' / 'Unknown').
* ``checks/retirement.py`` — Inspect the registry DB for retirement records and per-cell samples.
* ``checks/tensile_build.py`` — CPU-only Tensile build proof: does Tensile's own writer accept this phase?
* ``checks/tensile_build_probe.py`` — The Tensile-side proof machinery for the tensile-build check.

## oto/tools/ — offline corpus analysis

* ``tools/allruns.py`` — Best config per cell across ALL runs, and the knob reach per family.
* ``tools/chart.py`` — Visually pleasing comparison: native gfx90c vs gfx900-spoofed (floor).
* ``tools/consolidate.py`` — Deck consolidation: the CLI that dispatches to the four phases.
* ``tools/consolidate_deck.py`` — The measurement inventory and the deck selected from it.
* ``tools/consolidate_floor.py`` — The locked floor: plan it, materialise it, clone the registry under it.
* ``tools/consolidate_install.py`` — Installation: stage, install, and archive what is superseded.
* ``tools/consolidate_targets.py`` — Which cells a consolidated deck must address.
* ``tools/deck_review.py`` — The three questions to settle before decking a candidate or trusting a score.
* ``tools/potential_configs_gen.py`` — Automated potential_configs.md generator from run outputs.
* ``tools/verify_run.py`` — Corpus snapshot / diff / telemetry verification.

### ``tools/verifiers/``

* ``tools/verifiers/_evergreen.py`` — Shared machinery for the evergreen verification checks.
* ``tools/verifiers/_verdicts_worker.py`` — Shared verdict worker for the evergreen gate differential.
* ``tools/verifiers/verify_all.py`` — Orchestrator for the evergreen verification checks.
* ``tools/verifiers/verify_ast_equivalence.py`` — Evergreen symbol-level equivalence check.
* ``tools/verifiers/verify_config_writer.py`` — Evergreen config-writer equivalence.
* ``tools/verifiers/verify_gate_differential.py`` — Evergreen gate differential.
* ``tools/verifiers/verify_method_equivalence.py`` — Method-level equivalence: every TensileDriver method moved into a mixin, and every port_tensile function moved into a new module, must keep its exact body.
* ``tools/verifiers/verify_report_html.py`` — Evergreen HTML report check.

## oto/harness/ — the analysis harness

* ``harness/rows_ladders.py`` — Candidate row builders, part 1: the tile ladders and the batch literal.
* ``harness/rows_frontier.py`` — Candidate row builders, part 2: the tie-adapt and frontier blocks.
* ``harness/rows_smallcells.py`` — Candidate row builders, part 3: the small-cell evidence blocks.
* ``harness/asm_occupancy.py`` — Measured occupancy of every emitted Tensile kernel in the run corpus.
* ``harness/candidate_overlay.py`` — The candidate overlay: what is written, pruned and mirrored.
* ``harness/candidate_pool.py`` — The candidate loaders and the new module's helpers.
* ``harness/candidate_rows.py`` — The candidate row builders: per-family tile ladders and the auto rows.
* ``harness/cell_knob_diff.py`` — Per-cell native-vs-floor winner knob fingerprint diff.
* ``harness/corpus_census.py`` — Corpus census: what the corpus has ever measured, per family and per cell.
* ``harness/coverage_graph.py`` — Coverage graphs: the problem space as a 2D picture, and what is unexplored.
* ``harness/coverage_map.py`` — Coverage map: what the corpus has measured, and what it has not.
* ``harness/deck_probe.py`` — Deck check: does every *unmeasured* deck row actually build in Tensile?
* ``harness/failure_triage.py`` — Failed-candidate triage: which phases produced nothing, and why.
* ``harness/gate_calibration.py`` — Gate calibration: do the launch gates agree with what Tensile actually built?
* ``harness/generate_candidates.py`` — The candidate-generator CLI.
* ``harness/kernel_db.py`` — Ground-truth per-kernel-per-shape GFLOPS database.
* ``harness/measure_vgprs.py`` — Measure real per-thread VGPRs from Tensile-emitted code objects.
* ``harness/occupancy_bounds.py`` — Resident-workgroup audit per (family, shape) cell.
* ``harness/regression_matrix.py`` — Deck-vs-floor-vs-all-time cell regression matrix.
* ``harness/resolve_cells.py`` — Per-cell native-vs-floor winner resolution on the full knob surface.
* ``harness/rule_calibration.py`` — Rule calibration: would a *proposed* gate rule add false rejections?
* ``harness/tensile_probe.py`` — The legality oracle: ask Tensile itself whether a config builds.
* ``harness/visual_check.py`` — Visual/layout regression check for the acceptance report.

