# The ``oto/`` package map

Generated. Regenerate with ``python3 oto/_map.py``.

Each entry is the first sentence of that module's docstring, so the
only way to make this file stale is to delete the docstring. Line
counts are never quoted here -- they go wrong the day a file moves.

## oto/device/ — hardware facts

* ``device/peaks.py`` — gfx90c_common.py — Shared constants for gfx90c Tensile port

## oto/tensile/ — the Tensile-facing candidate pipeline

* ``tensile/candidate.py`` — Candidate generation: the family deck, the sampler, and the append boundary.
* ``tensile/candidate_config.py`` — The candidate payload dataclass.
* ``tensile/candidate_emission.py`` — The append boundary: how a candidate becomes a launchable phase.
* ``tensile/config_writer.py`` — The launch-boundary config writer.
* ``tensile/decks.py`` — The curated family tile decks: the starting candidates, and what kind each is.
* ``tensile/legality.py`` — Legality prior: manifest-derived legal domain + source-cited hard walls.
* ``tensile/library.py`` — The shipped gfx900 manifest: pinning, identity, and the rerun tier triage.
* ``tensile/library_parity.py`` — Coverage-parity rule: what the produced TensileLibrary may address.
* ``tensile/shipped_library.py`` — The shipped gfx900 library: locating it, parsing it, rebuiling a kernel from its name.

### ``tensile/gates/``

* ``tensile/gates/assembly.py`` — The assembly-class gate: is this GEMM class legal on gfx90c at all?
* ``tensile/gates/loads.py`` — Classic-path global-load divisibility, and the 16 B load-width cap.
* ``tensile/gates/occupancy.py`` — Register-file and LDS occupancy gates.
* ``tensile/gates/vgpr_model.py`` — The measured VGPR model: tables and budgets the occupancy gate cites.

### ``tensile/gfx90c_results/``


### ``tensile/synthesis/``

* ``tensile/synthesis/db.py`` — DB-hooked candidate synthesis: wide + narrow + direction mutants.
* ``tensile/synthesis/db_knobs.py`` — The forward-knob domains and tile vocabulary the DB-hooked mutator draws from.
* ``tensile/synthesis/db_patterns.py`` — The per-family mutation patterns for the DB-hooked mutator.
* ``tensile/synthesis/manifest.py`` — Coverage-guided constrained synthesis (Option H Phase 4, `Hplan.6`).

## oto/ledger/ — durable state + the mutation/convergence state machine

* ``ledger/agent.py`` — The convergence loop: harvest, mutate, decide, repeat.
* ``ledger/agent_coverage.py`` — Coverage guidance: what the ledger says about a cell, read once.
* ``ledger/harvest.py`` — Parent selection: which candidate a cell's next mutation starts from.
* ``ledger/mutator.py`` — The ledger-backed mutation arm: sampling, emission, outcome write-back, overlay.
* ``ledger/mutator_outcomes.py`` — Candidate classification: what a measured candidate turned out to be.
* ``ledger/proposals.py`` — The Option-H proposal ledger: emitted candidates and their measured outcomes.
* ``ledger/queries.py`` — The registry's read side: records, phases and run lookups.
* ``ledger/registry.py`` — The ledger: append-only records, runs, phases and the Option-H proposals.
* ``ledger/registry_core.py`` — registry_sqlite.py — SQLite-based registry for oto

## oto/metrics/ — turning benchmark rows into verdicts, reports and status

* ``metrics/ab_audit.py`` — Stage 7 acceptance A/B audit, and the CLI that prints it.
* ``metrics/ab_band.py`` — The acceptance band: how large a gap has to be before it is real.
* ``metrics/ab_delta.py`` — The native-vs-spoof A/B delta: the arithmetic every acceptance number rests on.
* ``metrics/ab_identity.py`` — A/B record identity: how the two arms are made comparable.
* ``metrics/ab_records.py`` — A/B record loading: the canonical (native, floor) inputs.
* ``metrics/analytics.py`` — Stage 5 analytics: CSV loading and per-cell aggregation.
* ``metrics/cell_status.py`` — Cell status: the RED / ORANGE / graded coverage classification.
* ``metrics/coverage.py`` — Coverage + fitness: cell states and LCB parent selection (Option H Phase 3).
* ``metrics/family_attribution.py`` — Cell/family attribution: which family a measurement row belongs to.
* ``metrics/policy.py`` — policy.py — Stage 4: Adaptive Repeat / Convergence & Run Policy
* ``metrics/read_thermals.py`` — The thermal envelope of one run, read from its telemetry CSV.
* ``metrics/render_status.py`` — The run-status text renderings and the live TTY panel.
* ``metrics/report.py`` — Stage 7 acceptance report: the verdict compute and the JSON writer.
* ``metrics/report_css.py`` — The dashboard's static assets: CSS and the three inline scripts.
* ``metrics/report_html.py`` — The acceptance dashboard renderer (JSON payload -> one HTML file).
* ``metrics/report_models.py`` — The report's two payload dataclasses.
* ``metrics/report_sections.py`` — The dashboard's HTML section builders.
* ``metrics/run_plan.py`` — The run plan and the cost model that prices it.
* ``metrics/run_status.py`` — Run status: the report builder, the renderers and the live panel.
* ``metrics/telemetry.py`` — telemetry.py: Minimal, non-root, systemd-distro sysfs amdgpu sensor reader.

### ``metrics/gfx90c_results/``


### ``metrics/gfx90c_runs/``


## oto/runners/ — execution

* ``runners/analytics_loaders.py`` — Corpus readers: how the driver loads measurements from every run.
* ``runners/auto.py`` — The ``--auto`` convergence loop: floor first, then tune to convergence.
* ``runners/auto_prompt.py`` — auto_prompt.py -- the questions every --auto run must ask first.
* ``runners/benchmark.py`` — Phase execution: the one place a Tensile subprocess is launched.
* ``runners/cli.py`` — The argparse stage dispatch: the ``port_tensile.py`` command line.
* ``runners/clocks.py`` — Per-phase telemetry clocks and the thermal envelope around them.
* ``runners/driver.py`` — The driver composition root: identity, toolchain, and wiring.
* ``runners/flags.py`` — The driver's argparse flags, one helper per group.
* ``runners/phases.py`` — The phase runner: manifest merge, policy filter, identical-fp skip bypass.
* ``runners/reference.py`` — The gfx900 reference floor: build, resume, and recall.
* ``runners/reporting.py`` — The acceptance report: verdicts, arms, and the emitted JSON.
* ``runners/synthesis.py`` — Stage 6: emit the per-family library logic and build it with TensileCreateLibrary.
* ``runners/timing.py`` — The three numbers that get conflated as "runtime".
* ``runners/toolchain.py`` — Toolchain discovery: the Tensile checkout and the ROCm toolchain.

## oto/checks/ — operator diagnostics

* ``checks/candidates.py`` — check_candidates.py — preflight every candidate config through the 4 legality gates.
* ``checks/db.py`` — Inspect the registry DB for label contamination ('auto' / 'Unknown').
* ``checks/library_parity.py`` — CPU-only enforcement of the TensileLibrary coverage-parity rule.
* ``checks/retirement.py`` — Inspect the registry DB for retirement records and per-cell sample counts.
* ``checks/tensile_build.py`` — CPU-only Tensile build proof for oto phases.

## oto/tools/ — offline corpus analysis

* ``tools/allruns.py`` — allruns.py — all-runs pattern analysis for oto.
* ``tools/consolidate.py`` — Deck consolidation: the CLI that dispatches to the four phases.
* ``tools/consolidate_deck.py`` — The measurement inventory and the deck selected from it.
* ``tools/consolidate_floor.py`` — The locked floor: plan it, materialise it, clone the registry under it.
* ``tools/consolidate_install.py`` — Installation: stage, install, and archive what is superseded.
* ``tools/consolidate_targets.py`` — Which cells a consolidated deck must address.
* ``tools/verify_run.py`` — verify_run.py -- prove a run was additive, and that its telemetry is usable.

## oto/harness/ — the analysis harness

* ``harness/candidate_overlay.py`` — The candidate overlay: what is written, pruned and mirrored.
* ``harness/candidate_pool.py`` — The candidate loaders and the new module's helpers.
* ``harness/candidate_rows.py`` — The candidate row builders: per-family tile ladders and the auto rows.
* ``harness/cell_knob_diff.py`` — harness.cell_knob_diff — per-cell native-vs-floor winner knob fingerprint diff.
* ``harness/generate_candidates.py`` — The candidate-generator CLI.
* ``harness/kernel_db.py`` — harness.kernel_db — ground-truth per-kernel-per-shape GFLOPS database.
* ``harness/measure_vgprs.py`` — harness.measure_vgprs — measure real per-thread VGPRs from Tensile-emitted code objects.
* ``harness/occupancy_audit.py`` — Resident-workgroup audit per (family, shape) cell — the "is occupancy ≤3?" tool.
* ``harness/regression_matrix.py`` — harness.regression_matrix — deck-vs-floor-vs-all-time cell regression matrix.
* ``harness/resolve_cells.py`` — harness.resolve_cells — per-cell native-vs-floor winner resolution on the full knob surface.

