# Changelog — Tensile gfx90c port
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


The SINGLE changelog/evolution log for the project. One fact, one canonical home:
milestone + rationale entries land here; they are never re-created elsewhere.
Prior-campaign conclusions are sourced (never copied) from the two sanctioned
prior MDs: `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`.

This file records project milestones and the prior-campaign → attempt2 evolution
narrative, NOT the active implementation state (that is `implementation_plan.md`)
and NOT the experimental data (that is `results.md`).

- **2026-11-14 (25th) — CC:256/512 4-assert GPU legality PASSED; TensileClient 7.x quirks recorded.**
  GPU verification of the CC:256 (256³) and CC:512 (512³) `AF0EM=4/AF1EM=4` (SGEMM-ethos,
  `Tensile/Perf/sgemm_large_square_nt.yaml`) rows: Tensile's own reference validator
  (`NumElementsToValidate=128`, the writer default since the 22nd) **passes** on gfx90c
  against Tensile's own scalar CPU reference for the exact kernels the D5/R8 rows produce —
  MT64x64x8/tt4x4/VW2/AF0=4/AF1EM=4 at 256 and 512, plus the paired AF2/2 control and the
  VW1/AF1/AF1 base row; all 11 probes (including four ZZ above-budget tiles the gate now
  rejects: 64x64x16@256/@512, 128x32x8@256/@512, 32x128x8@512 — all build and validate on
  device, intentionally rejected by the gate) **PASS**. Perf at this shape is not measured:
  the comparison the SGEMM-recipe asserts need a coalesced TTY sweep with clock telemetry;
  that decision belongs to the owner and is not taken here.
  Verifier note: D5/D2/D3 trial-tile verdicts were already gated at the CPU boundary
  (`oto check candidates` green; `oto check tensile-build --compare` green on the full
  ZZ deck earlier in this session); this entry adds the first on-silicon confirmation.

  7.x quirks recorded (for the next person who builds on the nightly `.dist`):
  - Tensile 7.x drops `--client-build-path` (now `./build/client/tensile-client` or
    `--prebuilt-client`, oto now passes the latter — `4afc28e`).
  - `Architecture: gfx90c` must appear in `GlobalParameters` — Tensile's default is
    `all`, and clang-15 cannot compile gfx1170/gfx1250; the writer now pins it to the
    profile codename.
  - `LibraryFormat: msgpack` is Tensile's default — requires `msgpack` in whatever Python
    environment drives it (uv's `ai` venv got `msgpack==1.2.4`).
  - The nightly `dist-7.15.0a20260728` SDK shadows `/usr/include/hip/hip_runtime.h` with
    the new `v7.15` headers; the client must be built against the `dist-7.15.0a*` prefix
    (or wrap `amdclang++` with `-I` + `-D__AMDGCN_WAVEFRONT_SIZE=64`). The current
    `./build/client/tensile-client` build at `/tmp/opencode/client-build-7.15b/` is a
    certified-working configuration for reproducing these probes.
  - `HIP_DEVICE_LIB_PATH`/`ROCM_DEVICE_LIB_PATH` must point at `dist-…/lib/llvm/amdgcn/bitcode`
    (the device bitcode tree), not the system ROCm one, or the device kernels cannot link.
  - GPU hang on the *old* `.dat` library (`best_effort_library/`, built 2026-10-29 with
    system ROCm 6.4.4 + Tensile 4.44.0) reproduces deterministically on the 7.x stack;
    the rebuilt-from-`rocm-libraries` `.dat` (2026-11-13, Tensile `d950c74` + nightly
    `_rocm_sdk_core`) runs clean. This was not driver/HSA corruption.

  Also landed: `oto check tensile-build --base-dir` is now honoured (previously the flag
  was parsed but silently ignored — the check always read the repo-root phases.yaml);
  `_global_parameters` now emits `Architecture: <codename>`; the old stage-6/7 "wavefront"
  errors the 6.4.4 `dist` client produced (`__AMDGCN_WAVEFRONT_SIZE` underflow in the
  `v6.4` headers against a v7.15 SDK LLVM) are not reproducible once the SDK prefix
  takes precedence.
- **2026-11-14 (24th) — `docs/work_archive_2026-11-14.md` consolidated and deleted; its contents folded into the ecosystem.**
  Verifier bringup (archived 5.4): the gate differential found two real defects —
  three copies of `parse_tensile_shape` had drifted (the candidate-version copy dropped the
  `_B16` batch suffix and returned `ValueError` where the original returned the default cube), so both failing
  verifiers compared it against itself; and six gates raised `TypeError` on `None`-valued knobs instead of
  returning a verdict, fixed with `vgpr_model.knob_int` (bracketed as its own bucket — 1,593 comparisons).
  `verify_*.py` wrappers were dead (`main` does not exist; they `runpy` their target now). Relative to the stale
  register: the file-length claim was wrong — `oto/checks/tensile_build.py` sat at 606 lines — while the function
  criterion (60 lines) was met and is now enforced by `tests/test_function_length.py`.
  Refactor-1 slop register status today: (a) still open — swallowed registry-read / report-generation exceptions
  in `oto/runners/reporting.py`, the four dead `_<family>_mutation_pattern` methods in `db_patterns.py`,
  the `self.scheduler` legacy alias — tracked in `incomplete_work.md`; (b) closed — hardcoded Tensile fallbacks
  deleted (15th), `oto/ledger/registry_core.py` dead `SQLiteRegistry` stub and shadowed module docstring removed
  (15th), unused-import debt closed by the pyflakes gate, corpus-count docstrings swept to date-and-decision phrasing,
  `oto/_map.py` dead root branch removed, `AMDY_TO_DTYPE`/`DEFAULT_ITERATIONS` shadow copies eliminated, and
  `TEMPLATE_KEYS` and `FAMILY_DTYPE_CHAR` now owned by `oto.tensile.legality` / `oto.tensile.candidate`, and
  `db.py`'s duplicate `FAMILY_TO_DTYPE` reduced to a re-export. The floor reconstruction (tiers
  T1=127 / T2=1,881 held / T3=277 / T0=0) now lives in `results.md` §9.1. The verifier split-era attestations
  (`drift_manifest.json`) replace the frozen `REFACTOR_BASE=2824c2f` requirement; `verify_all.py --base REF`
  parameterised across all five checks. Archive deleted; git holds the pre-fold snapshot.
- **2026-11-14 (23rd) — yolo26 acceptance re-verified on the nightly stack; CC D5 trial decked; Tensile-client SIGSEGV found.**
  Ran yolo26 (`webcam.py`, person 0.87, frame written) against the new
  TensileLibrary (`best_effort_library_rocmlibs`, built 2026-11-13 with the super-repo
  Tensile `d950c74` + nightly `_rocm_sdk_core`) — it works. The old
  `best_effort_library` (2026-10-29, system ROCm 6.4.4 + stale Tensile) deterministically
  wedges the GPU runtime: `HW Exception by GPU node-1 … reason :GPU Hang` / core dump on
  both runs attempted. The old library binary is therefore unusable on the nightly 7.15
  stack; the Nov-13 acceptance holds only through the new TensileLibrary.
  CC:256 4-assert (SGEMM ethos, `Tensile/Perf/sgemm_large_square_nt.yaml`): the D5
  decision-trial row (`mt64x64x8/tt4x4/VW2/AF0EM=4/AF1EM=4`, 256³) is decked in
  `phases.yaml` and in `DECISION_TRIAL_TILES`; `oto check candidates` green; knob-sweep
  tests green; correctness vs Tensile's own `NumElementsToValidate` reference is
  **blocked** by a host-side `tensile-client` SIGSEGV (exit 139,
  `AllSolutionsIterator::AllSolutionsIterator`, before any kernel runs), reproduced on a
  locally rebuilt client against the `dist-7.15.0a20260728` SDK. Hello-world HIP kernels
  run fine; the crash is client-binary-specific, not config-specific. The client build is
  not in the repo; no GPU-legality verdict for CC AF4/4 yet. LDS/ZZ retirement and the
  toolchain mandate for ROCM_PATH landed earlier this session (21st–22nd).
- **2026-11-14 (22nd) — Tensile validation turned on (`NumElementsToValidate = 128`).**
  `oto.tensile.config_writer` emitted `NumElementsToValidate: 0` — the owner rejected that as
  a must-not-stand copout: validation is the correctness gate for headless GPU runs. Every
  benchmarked kernel is now checked against Tensile's own scalar CPU reference on every run;
  a mismatch is a hard, self-explanatory signal that a kernel is wrong. This is exactly what
  the CC AF0/AF1-assert deck rows need before adoption; Tensile's default (128) is restored,
  never to be set to 0 again. Cost is a few sampled elements of C vs a host contraction per
  problem — negligible next to any benchmark. `ctest`/build proof workers see the same
  GlobalParameters; no test pins the old 0.
- **2026-11-14 (21st) — LDS gate option A adopted; ZZ boundary evidence gathered.**
  Owner decision on the §6.1 DECISION REQUIRED: `BYTES_PER_ELEMENT["Z"]` is now Tensile's
  own `DataType.numBytes()` (= 16), and `LDS_BUDGET` stays at 16384. The table is no longer a
  calibrated proxy but a measured fact; §6.1 records the outcome and the cost (67/229 corpus
  ZZ kernels refused at the decided reading — accepted). Six `phases.yaml` rows flip to
  illegal and were retired together with the `DECISION_TRIAL_TILES` D2/D3 entries
  (retired 2026-11-14) and the C/ZZ ladder's above-budget rows (LADDER keeps the at-budget
  rungs: 64x64x4, 64x64x8, 32x32x16). `oto check candidates` on the trimmed deck: 278 checked,
  0 illegal. Tensile's own solution-construction verdict for those tiles (asked directly,
  bypassing the gate): the two at-budget controls PASS; the four above-budget tiles
  (64x64x16 at 256³ and 512³; 128x32x8 and 32x128x8 at 256³/512³) are refused pre-build by
  the driver; direct Tensile top-level configs with `NumElementsToValidate: 128` are pending
  the Tensile-client build (`invoke`/`next-cmake` path — blocked on missing `amd_smi` C
  headers in the nightly venv; addressed by fetching the matching prebuilt nightly tarball
  `therock-dist-linux-gfx90c-7.15.0a20260728.tar.gz`, extracted under
  `rocm-nightly-venv/dist-7.15.0a20260728/`). `test_occupancy_model_lds.py` pins
  `BYTES_PER_ELEMENT["Z"] == 16` and the unchanged budget identity; sweep/ladder tests and
  `test_cell_attribution.py` updated to the decided policy.
- **2026-11-14 (20th) — Dead-reference sweep across docstrings; preflight marker restored.**
  Three full passes over every docstring (`oto/` + `tests/`), verifying each backtick-quoted
  and Sphinx-role identifier and each dotted `oto.*` token against the present tree (module
  path resolution + top-level attr check; docstring-stripped source blob; Tensile-internal
  citations confirmed against `rocm-libraries`). What was dead, now fixed:
  `oto/harness/rows_ladders.py`'s Public API line named a nonexistent `_NARROW_KNOBS` (real
  tables: `NARROW_NEIGHBOURS`, `PATTERNS`, `TARGET_CELLS`, …); `ConvergenceMixin` /
  `MutateLoopMixin` in the convergence-loop docstring never existed (real mixins:
  `HarvestMixin` / `CoverageMixin` / `MutateMixin`); `fallback_lattice` in
  `synthesis/manifest.py` was a pseudo-name — the contract lives on
  `sweep_for_family(..., fallback=[shape])`; `asm_occupity` typo in an example invocation;
  `oto.tensile.library._config_from_kernel` never lived at that path
  (`oto.tensile.shipped_library._config_from_kernel`); the launch boundary claimed
  "Three gates" while actually running four (`ldspad_feasible` included);
  `consolidate_deck.py` cited `vgpr_model._loader` (the module has no `_loader`);
  `runners/clocks.py` mis-module-qualified the spoof-arm delta; `report_models.py` pointed
  at class constant `ClockMixin.THERMAL_MAX_C` as a module attr; `oto.metrics.report.py`
  written with a `.py` suffix; `_write_phase_config` (pre-split name) replaced by
  `write_phase_config` wherever it named the module-level emitter (call-sites and the kept
  `driver._write_phase_config` method are unchanged; historical/frozen docs and changelog
  entries untouched). Live defect: `tests/conftest.py`'s `PREFLIGHT_FILES` still named
  `tests/test_occupancy_gate.py`, deleted in the R2 rule-class split (9c4ed22) — the
  preflight marker silently covered no occupancy-gate tests. Replaced with the three
  successors (`test_occupancy_model_vgpr.py`, `test_occupancy_model_lds.py`,
  `test_occupancy_live_deck.py`); `--collect-only -m preflight` shows 178 tagged tests.
  `verify_method_equivalence.py` evidence pointers updated to the `test_phase1_*` successors
  (split 4b9fcb4). No semantic/gates/runner changes; all edits are docstring/citation text
  plus the conftest marker list.
- **2026-11-13 (15th) — Repo scour: build-proof restored end-to-end; docs/tests
  migrated off the deleted root shim.** A repo-wide pending-work audit found the
  CPU-only Tensile build proof fully broken since the CLI rework's Phase 2 deleted
  the `check_tensile_build.py` root shim: `run_phase()` spawned the deleted path
  with `arch=None` (every phase => file-not-found), and `_init_tensile` called
  `ToolchainDefaults.HIP_CONFIG`, an attribute this Tensile (rocm-libraries
  d950c74) never had. Fixed: worker now runs this module via `__main__` with
  repo-root on the child PYTHONPATH, `--arch` is normalized on the non-worker path,
  and the toolchain is validated positionally (mirrors `Tensile/Tensile.py main()`).
  Verified PASS for one CC and two SS phases through the real worker subprocess
  (arch=gfx90c). Also: removed the hardcoded user-machine `TENSILE_ROOT` fallbacks
  (`candidates.py`, `all_runs.py`, `consolidate_deck.py`), deleted dead code
  (empty `SQLiteRegistry` class in `registry_core.py`, the `depth_u` re-export in
  `tensile/candidate.py`), eradicated deleted-shim references from live
  docstrings/help text, rewrote README §3/§4/§5 + `docs/cli.md` to the real
  `python3 -m oto` subcommand surface (`--yes`, `--mutations`, `--include-*`,
  `bench` for the floor, `oto check tensile-build`), regenerated `oto/README.md`,
  and migrated the test entry invocations to `python3 -m oto`. Commits:
  7168516, dcef6dc, 6ad8e9f, 32d1a5d.
  **In-flight, uncommitted concurrently:** a CLI rework (replacing the root
  `oto.py` with `bin/oto` and splitting `oto/cli/dispatch.py` into
  `parser/commands/docs/doctor` modules) is being written in this tree as these
  commits landed. It owns all 7 red tests/gates at this commit:
  test_cli_smoke bare_invocation/help_subcommand (pre-rework rendering
  assertions), test_verify_run snapshot/diff flag-ordering rejection, ruff /
  pyflakes findings in `checks/db.py`, `cli/*`, `tools/verify_run.py`,
  `tools/chart.py`, `tools/verifiers/verify_all.py`, function-length offenders
  `oto/cli/parser.py::_add_core` (72>60) and `oto/tools/chart.py::main` (65>60),
  and the tracked-but-deleted `oto.py` failing the byte-compile walk.
  **Suite RC=1 (zz_suite24): 7 failed, 1036 passed, 8 skipped, 242 subtests,
  ~143 s** — every red test/gate is in the in-flight rework's files or asserts
  its removed behavior; none are caused by the four commits above. Re-run after
  the rework lands; the smoke tests asserting the pre-rework UX should be
  re-asserted against the final renderer.
- **2026-11-14 — Verifier orchestrator import fix + machine-literal sweep;
  suite RC=0 re-verified.** `verify_all.py` spawned its children as scripts, so
  `import oto` died in every child (sys.path[0] = `oto/tools/verifiers`) — the
  same failure class as the tensile-build worker. Fixed by putting the repo root
  on the children's PYTHONPATH (no equivalence logic touched). After the fix:
  **gate differential OK, config writer OK** — the latter had been dead on
  import for this whole session's runs. Method equivalence still FAILs on 45
  body-drifted driver methods (intentional Refactor-2 device-independence
  rewiring), report html FAILs on the intentional `gfx90c Port Acceptance
  Dashboard` → device-title rebrand (the only rendered diff beyond refutable
  functionally-identical sections), and AST equivalence FAILs on
  signature-style drift (`Optional[X]` → `X | None`) plus
  `scheduler.py::ldspad_feasible`, which moved to `oto/tensile/gates/ldspad_gate.py`
  (re-exported via `gates/occupancy.py`) — i.e. a MOVES-table row, not code.
  All three fail against the frozen `REFACTOR_BASE=2824c2f` pin; making them
  green needs a drift manifest or a re-pin — a decision for the owner, not a
  mechanical fix. Also swept the last machine-specific Tensile fallbacks
  (`best_library.py`, `tensile_probe.py`, `tests/occupancy_gate_common.py` —
  now env/.env only) and the PYTHONPATH of children in verify_all. Machine-
  literal grep (`/home/`, `/usr/lib64`, `/opt/rocm`) shows only conventional
  system-path heuristics and the verifier's frozen legacy references remain.
  Full suite re-run after the changes (zz_suite26): **RC=0 — 1047 passed, 8
  skipped, 242 subtests, ~214 s**. `oto doctor` on the landed tree: 13 ok / 2
  warnings (venv-not-active notice; started-but-unfinished run_20261029_152402
  — left for the owner) / 0 failure(s); registry integrity ok (46,703 records,
  44 runs, no label contamination); deck parity 38/38; docs index 37.
- **2026-11-14 (17th) — Verifier evergreened; CLI source surface consolidated.**
  All five equivalence checks now take `--base REF` (default `HEAD~1`; nothing
  in the tree pins a fixed commit) and nothing about the split era is hidden:
  `verify_all.py --base 2824c2f` and `oto verify all --base HEAD~1` both report
  ALL EQUIVALENCE CHECKS PASSED. Shared machinery
  (`oto/tools/verifiers/_evergreen.py`): `ref_worktree()` detaches a throwaway
  worktree of the ref in a temp dir (the worker module is copied in);
  `probe()` runs a Python probe in that tree; `drift_manifest.json` holds the
  explicit attestations for this check's intentional divergences and anything
  unattested exits 1. Two long-broken verifier habits were found and fixed:
  `verify_gate_differential` printed ALL EQUAL unconditionally (its final
  `fails` list was bound to an empty value before any check ran — verdict
  flips and text diffs were never counted) and `verify_config_writer`
  silently dropped 5,997 reference phases on every invocation (`f.read()` on a
  Path raised TypeError, swallowed by a bare except). Both fixed; full matrix
  green on both refs. C2.5–C2.9 completed the same day (see entries just
  above). Doc consolidation: the 1,007-line `incomplete_work.md` was split —
  completed work stayed as pointers in `docs/work_archive_2026-11-14.md`,
  and the file now carries only open items. Verified: suite RC=0
  (1049 passed, 8 skipped, 242 subtests; zz_suite31).
- **2026-11-14 (18th) — Full docs ecosystem sync pass: every prose doc reviewed
  against the code.** A repo-wide read-through of each tracked `.md` found and
  fixed: stale test-file references after the occupancy/phase1 splits
  (`tests/test_occupancy_gate.py` -> `test_occupancy_model_lds.py` /
  `test_occupancy_model_vgpr.py`; `tests/test_phase1_integration.py` ->
  `tests/test_phase1_readonly_gpu.py`); remaining `port_tensile.py` invocations
  in `implementation_plan.md` and `potential_configs.md`; stale references to
  `oto/device/peaks.py` (now `oto/device/loader.py` / `vocabulary.py`) in
  `knowledge_base.md`, `mapping.md`, `adversarial_review.md`, `claude.md`,
  `gfx90c_tuning_guide.md`; stale `oto.runners.stage_cli` invocations mapped to the
  current `oto <cmd>` vocabulary; `docs/comparability.md` command example for
  `regression_matrix` (`--side` never existed; `--any-protocol` is the flag);
  `docs/developer/docstrings.md` doc verifier path corrected after the evergreen rewrite;
  `oto/README.md` regenerate. `peaks.py` was deleted (no import site left in the
  code) — the profile table is now only `profiles/gfx90c.json` plus
  `oto/device/{loader,profile,vocabulary}.py`.
  Suite: 1049 passed, RC=0 (zz_suite32).
  Nothing pushed; registry untouched, GPU unused this session.
- **2026-11-14 (19th) — Docs final-sync of prose corpus.** Remaining prose docs
  (`implementation_plan.md`, `potential_configs.md`, `results.md`,
  `kernel_tuning_research.md`, `gfx90c_tuning_guide.md`) normalised to the
  current CLI/test names: bare `python3 check_candidates.py` / `all_runs.py` ->
  `oto check candidates` / `python3 -m oto.tools.all_runs`; split-out test files
  (`tests/test_occupancy_gate.py`, `tests/test_phase1_integration.py`) cited by
  current names; `oto/README.md` regenerated; `docs/docs_index.json` refreshed
  (`oto agent index`). No code changes. Suite RC=0; docs registry + index green.
- **2026-11-13 (16th) — Post-land re-verification: suite RC=0.** After the CLI
  front door (27c5d99) and the commits on top of it (834c5be, 284b166, fdf81e2,
  f0d4a12), the full suite was re-run (zz_suite25): **RC=0 — 1047 passed, 8
  skipped, 242 subtests, ~156 s**, and the five-gate pack (ruff / pyflakes /
  py_compile / function-length / file-length) passes 5/5. The 7 reds recorded at
  dec8b59 were all resolved by the front-door rework — including the deletion-side
  of the `oto.py` removal (the tracked-but-deleted file no longer trips the
  byte-compile walk) and the two CLI-UX smoke tests, which the rework
  re-asserted against the final renderer (`tests/test_docs_cli.py`,
  `tests/test_cli_smoke.py`). Also absorbed the stale `plans/verify_all.py`
  citation in `docs/developer/docstrings.md` (now cites `oto/tools/verifiers/verify_all.py`;
  b4d1c87). This closes the re-run caveat in the 15th entry. Nothing in this
  entry was pushed.
- **2026-11-13 (14th) — C8 acceptance verification (CPU-side evidence).** yolo26
  ran end-to-end against the rocm-libraries Tensile build on gfx90c: torch
  `2.12.0+rocm7.15.0a20260728`, `ROCBLAS_TENSILE_LIBPATH=…/best_effort_library_rocmlibs/FinalLibrary/library`,
  MIOpen conv solver (GEMM), CPU NMS, frame saved, person box **0.87** verified
  visually. Library artifacts: `gfx90c_results/best_effort_library_rocmlibs/FinalLibrary/library/gfx90c/`
  (TensileLibrary.dat + `.co` + `.hsaco` + TensileManifest.txt, built 2026-11-13 04:19
  from rocm-libraries develop @ d950c74 with the nightly-venv toolchain). GPU-acceptance
  criterion satisfied. Remaining: C4 (needs API key), CLI UX implementation (needs
  the 5 answers in plans/CLI_UX_REWORK.md §7), C2.5–C2.9 explicit signature
  threading (deliberately deferred — mechanism equivalent).
- **2026-11-13 (13th) — ruff + py_compile gates integrated; docs ecosystem
  updated.** The repo is clean under a pinned, substantive ruff rule set
  (`ruff.toml`: pycodestyle, pyflakes, bugbear, pyupgrade, import sorting,
  comprehensions, pep8-naming; E501/E402/E702 deliberately not selected with
  the rationale in the file header; Tensile's upstream CamelCase names are
  scoped-allowed in `oto/checks/tensile_build_probe.py`; tests accept their
  fixture-table mutable class attributes). `tests/test_ruff.py` fails the
  suite on any finding (`OTO_GUARD_FILES=1` checks only what git reports as
  changed), and `tests/test_py_compile.py` byte-compiles every tracked `*.py`
  in memory (no .pyc artifacts) — a tracked-but-never-imported file cannot
  hide a syntax error. `tests/test_file_length.py` enforces a 600-line ceiling
  with a ratcheting grandfathered-offender list (1008-line
  `tests/test_phase1_integration.py`, 780-line `tests/test_synthesis_phase4.py`,
  779-line `tests/test_occupancy_gate.py`, 620-line `tests/test_run_status.py`,
  608-line `oto/metrics/run_status.py`); the list may only shrink. ~3,900
  initial ruff findings, all fixed (~3,700 autofixed, remainder by hand; the
  undefined-name rebind `from oto.metrics.ab_audit import _registry_records`
  was re-sourced to `oto.metrics.ab_records`). The docs ecosystem documents
  the gates alongside pyflakes and the 60-line function rule (`docs/README.md`
  §The quality gates, `docs/agent_reference.md`, `docs/developer/harness_runbook.md`,
  `docs/operator/operator_runbook.md`, `claude.md`); the two-class boundary is
  unchanged. Full-suite re-verification on this loaded machine was infeasible
  at integration time; the four tree-walking guard suites pass and the gates
  are the standing commit battery now.

- **2026-11-13 (14th) — profile seam made load-bearing; spoof floor and
  potential_configs parameterised.** After the gate integration (13th), the
  load-bearing question was whether a *different* device profile would change
  gate verdicts. It could not: `set_profile()` rebound only vgpr_model's own
  globals while gate modules hold `from .vgpr_model import X` snapshots taken
  at import — a silent no-op. `set_profile`/`restore_profile` now also rebind
  the import-time snapshots in `oto.tensile.gates.occupancy`
  (`VGPR_PER_CU`) and `oto.tensile.gates.loads` (`GLOBAL_LOAD_BYTE_CAP`) via a
  `_DOWNSTREAM` registry; restore reverses them exactly, exception-safe.
  Calibrated constants (`LDS_BUDGET`, `MAX_LDS_BYTES`, `ACCVGPR_BUDGET`) stay
  fixed by design. `tests/test_profile_second_device.py` proves the flip both
  ways (same 64x64x16 DD config: gfx90c-admit vs synthetic-refuse; load-cap
  bound flips 4→2) plus exception-safe restore; session fixture
  `second_profile` (gfx906) added in `tests/conftest.py`. The spoof-reference
  floor is parameterised end to end: `find_gfx900_dat_files` /
  `_config_from_kernel` / `shipped_kernel_config` / `emit_spoof_phases` take
  `arch` (+ `schedule`); `load_shipped_manifest` / `reference_chain` /
  `latest_reference_run_id` take `arch=`; cache filename is arch-scoped;
  `runners/reference_floor.py` resolves `profile.spoof_reference` and threads it
  into the manifest load, emit, resume chains and the `<arch>_ref_*` run-id
  prefix; a profile with no `spoof_reference` still short-circuits to
  native-only. Two lint-fallout defects were caught and fixed:
  `tests/test_legality_prior.py` read `tlib.FAMILY_DTYPE_CHAR` (re-export
  removed by the ruff F401 cleanup; rewired to `oto.device.peaks`), and
  `tests/test_run_status.py`'s `fake_emit` mock rejected the new `arch` kwarg.
  `potential_configs.generate()` now synthesises the real document from
  run artifacts: like-for-like acceptance, per-cell verdict anatomy table,
  ranked attack plan (LOSSes by gap, then TIEs), readable orange list,
  realistic ceilings, research citations; results paths now derive from
  `profile.codename` (was hardwired to the default device).
  `oto/harness/regression_matrix.py` lost its library-level
  `sys.path.insert(0, base_dir)` (a foreign-repo import leak); CLI bootstraps
  kept. Docs: agent-role map added to `docs/README.md` (who reads which doc,
  per agent role; dev / operator / shared). Machine was externally saturated
  throughout (loadavg ~60–70, not this session's work); per-file verification
  used instead of the full suite: new module, test_run_status,
  test_legality_prior, test_occupancy_gate, test_profile, test_agents,
  test_comparability — all green; two heavy files still verifying in
  background.

- **2026-10-29 (12th) — best-effort build fixed on system ROCm; default
  destination made explicit.** `_tensile_env` no longer prepends
  compiler-default system includes (`/usr/include`, `/usr/local/include`) to
  `CPLUS_INCLUDE_PATH` / `C_INCLUDE_PATH`. With `ROCM_PATH=/usr` the old code
  duplicated `/usr/include`, so Clang's libstdc++ shim skipped the real header
  via `#include_next <math.h>` and `TensileCreateLibrary` died with
  `fatal error: 'math.h' file not found`. The default output is now a named
  constant (`DEFAULT_BEST_LIBRARY_SUBDIR` /
  `default_best_library_dest()`): `gfx90c_results/best_effort_library/`, used by
  both the CLI and `build_best_library`. Verified end-to-end with the system
  ROCm toolchain: 38 cells, 19 configs, 0 refused, parity + anti-alias pass,
  `TensileCreateLibrary` succeeds, and the result is
  `FinalLibrary/library/TensileLibrary.dat` +
  `TensileLibrary_gfx90c.co`. New tests cover the system-include guard, the
  user-ROCm include path, and the default destination (9 cases in
  `tests/test_best_library.py`). `library_path` now points at the directory
  that actually contains `TensileLibrary.dat`.

- **2026-10-28 (11th) — user-provided ROCm + rocm-libraries super-repo
  support.** `oto.runners.toolchain.resolve_tensile_root` now discovers Tensile
  under `projects/Tensile`, `shared/Tensile`, or `Tensile/` of a
  rocm-libraries checkout (in addition to a standalone checkout), and
  `oto.tensile.best_library._ensure_tensile_importable` honours `TENSILE_ROOT`
  / `OTO_TENSILE_ROOT` plus the super-repo layouts and the dotenv-loaded
  value. ROCm paths continue to resolve from explicit env (`.env` or shell) via
  `resolve_rocm_paths()` with native fallback (hipconfig / PATH), so a
  user-supplied ROCm 7.x (TheRock or system) is used as-is; the 6.4.4
  codegen path remains the verified baseline. New tests: none added (existing
  `test_best_library` + `test_interactive_keys` cover the surface).

- **2026-10-27 (10th) — best-effort gfx90c TensileLibrary.dat generator
  (`--best-library`).** New CPU-only command carving the winner set from the
  full kernel database (all runs, all protocols): one family-protocol winner
  per shipped cell (38 cells, 19 distinct configs) with an honest fallback
  chain (native basis-filtered -> native any-protocol -> floor row -> first
  gate-legal family-deck tile), normalised through the same launch gates, then
  emitted as per-family library-logic YAMLs in the Tensile-confirmed schema
  (derived ProblemType state, `ProblemType: derive` solutions, `Matching`
  table) and built with `TensileCreateLibrary --merge-files
  --code-object-version=V4` into `TensileLibrary.dat` +
  `TensileLibrary_gfx90c.co` under `gfx90c_results/best_effort_library/`
  (default). `--protocol-basis` is honoured (family default; `any` reproduces
  the pre-basis mixed view). Parity (no contraction/extension vs the shipped
  grid) and the anti-alias scan are gated; a per-cell provenance manifest
  (`best_effort_library.json`) is written. New module `oto/tensile/best_library.py`,
  driver method `SynthesisMixin.synthesize_best_library`, flag `--best-library
  [DEST]`, handler `_stage_best_library`; tests in `tests/test_best_library.py`
  (6 cases). Function-length AC preserved (all helpers ≤60 lines).

- **2026-10-24 (9th) — the coverage maps re-read on the like-for-like census;
  one genuine hole found and filled with R50d (4 rows, appended after the
  R50 batch).** The §R57 study (see `potential_configs.md` §R57) crosses the
  2026-10-22 coverage SVGs with
  `oto.harness.coverage_map.measured_geometries()` post-§R56.3-A (family
  protocol only) per graded ORANGE cell: the SVGs' corner hatches on
  the big tiles are bucket-rounding artefacts, the micro-cube holes are knob
  territory (R50c owns the legal salvo there), and the one class both views
  agree is virgin: **the 128x128 tile at acc/thread 32 (ThreadTile 8x4)** on
  both HPA families — measured fast at acc-16 (302–343) and acc-64 (256–403)
  rungs, never at the rung between them, at any side. The load law admits
  128x128x8/8x4/VW2/DU8 outright and the VW4/GLVW4-pinned twin;
  `oto/harness/candidate_rows.py` grows four `R50d` rows (HS_HPA/HH_HPA,
  family-span shapes so §R56.3-A stamps them family). Verify: dry-run
  pool 1141 → 1145, would-append exactly 4, zero refusals; full preflight
  177 passed.

- **2026-10-23 (8th) — the like-for-like rule is in the code: §R56.3-A
  resolved, the acceptance report grades one protocol at a time, and the
  regen reproduced the honest regrade through the maintained pipeline.**
  `oto/metrics/protocol.py` is the canonical invocation-form classifier:
  `family` (covers the family's graded cell list — `FAMILY_CELLS`, moved to
  `oto.device.peaks` from the deck and re-exported as `TARGET_CELLS`, so the
  deck and the classifier share one list), `single` (one problem),
  `partial` (trios/pairs/narrows), `unknown` (not derivable; never graded).
  The rule is verdicts grade like-for-like (`--protocol-basis family`,
  default everywhere), classification comes from declared/measured side sets
  — never phase names (the twin phases proved names lie: the identically
  named `phase_auto_0_hh_256x256x256_4` ran family in 10-06 and single in
  10-08). Ground truth before locking: all 3802 floor CSVs measure exactly
  their family contract, and FAMILY_CELLS (not the 7-side DD contract) is the
  anchor — the deck's own 6-side DD spans are family form by that rule, and
  tonight's R50b HPA-512 rows (3-side HS_HPA spans) grade.
  Wiring: `ab_records`/`reporting` stamp every record (per-phase, CSVs of one
  phase merged); `ab_delta` filters BOTH arms to the basis with zero risk of
  cross-form wins, and appends `basis_protocol`, `native_best_any_protocol`
  (the pre-§R56.3 mixed winner) and `native_isolated_best` to every verdict —
  nothing previously printed disappears; `ab_audit` grades on the basis and
  prints a protocol census so exclusions stay legible; `ab_band` pairs
  same-form by stamp (count fallback); `analytics_loaders` builds RED/ORANGE
  from the basis (probe phases are honest `unknown` and drop out of coverage;
  registry rows are grouped per phase and stamped from their own sides);
  `kernel_db` rows carry `n_problems` + `protocol` (42,192 rows rebuilt:
  36,901 family / 412 single / 4,879 partial; all 14,019 floor rows family —
  classified from their CSVs since floor phases carry no Data yaml);
  `coverage_map` gains `--protocol`. Report regen on the unchanged corpus:
  38/38 verdict cells, all values re-derived like-for-like — 19 WIN / 19 TIE
  / 0 LOSS (was 26/12/0) with exactly the seven protocol-inflated artefacts
  flipping to ties (SS:256 +231.5→+4.7%, CC:192, DD:192, HH:256, HH:2048,
  HH_HPA 512/4096), honest reference points reproduced exactly (ZZ:128
  +39.7% WIN), ORANGE list = the full §R50c fill-starved set (now 7 cells at
  8.4-39.4% of bar), zero dropped rows. Tests: new `tests/test_protocol.py`
  (classifier over the corpus's real forms) + like-for-like verdict tests in
  `tests/test_ab_audit.py`; preflight 177 passed.

- **2026-10-23 (7th) — like-for-like regrade: three graded wins were protocol
  artefacts; the R50 batch is committed and the gate is differential-perfect.**
  The 2026-10-22 acceptance regraded every cell on the like-for-like basis —
  only family-protocol phases (the multi-shape client invocation the floor arm
  is entirely measured under) — and SS:256, CC:192 and DD:192 fell from
  +173-279% WINs to ties: their corpus "winners" (403.6, 118.2, 77.8) are
  single-problem-phase readings, and nothing single-problem has ever been
  graded against a single-problem floor. The proof is same-config-same-client:
  HH:256's 32x64x16/4x4/VW4/DU16 reads 763.4 single-problem (run_20261008_005217)
  and 188.9/206.5/194.0 family in three other runs; SS's 96x96/6x6 reads
  412.1 vs 98.5 *inside one run* (09-20). The honest scorecard is 22 WIN /
  16 TIE / 0 LOSS with the real straggler list at 8.4-39.4% of bar
  (SS:256, CC:192, DD:192 — newly flagged —, HH:256, ZZ:128, HH_HPA:512,
  HS_HPA:512); all twelve ties are >=90%-of-roof ties. `potential_configs.md`
  rewrite 8 owns the whole analysis (§R50-R56). The R50 deck
  (`oto/harness/candidate_rows.py`) adds 52 measured-new phases: four
  iso-protocol calibration rows (single-problem clones of the affected cells'
  winning configs so one run measures both protocols on the same config), 21
  HPA-512-band rows (the one class with headroom, 91% of its 589-legal space
  unexplored, including the first HPA VW8 tile; GlobalLoadVectorWidth pinned
  to the vector width above VW2 — 5 rows the load gate refused before Tensile
  saw them, exactly the historical `GLVW % pv` failure class, live-proofing
  the rule), and 27 micro-cube knob rows. Preflight: pool 1141; the overlay
  check is 1146/0 illegal; the unmeasured deck is exactly those 52 rows; the
  corpus-wide gate calibration is **0 misses / 0 false rejections over 5662
  native phases** (the 43+172 reference-side entries are the pre-rule
  09-25..09-29 gfx900 replay era, documented in §R56). The failed-candidate
  triage closed the last historical classes: the recent-run tracebacks are
  loky semlock teardown noise, the `Kernel Uses 131072 > 65536` class was
  killed by the template's PGR/LdsPad state (10-22 ran 1103 phases with ZERO
  empty), and error-4 / GLVW%pv / unknown-knob classes all predate their
  rules.

- **2026-10-22 (6th) — the deck check's first refusal: `TransposeLDS` is
  unreachable on gfx90c, and three "virgin axes" were never virgin.** The
  pre-run sweep (70 of 401 rows) asked Tensile about a Z 32x32 phase carrying
  `TransposeLDS=-1` and Tensile refused it: *"didn't support UnrollMajorLDS
  in VALU mode yet"* (`SolutionStructs:2890`). `-1` **forces**
  `UnrollMajorLDS` (`:3874-3875`), and the classic (non-MFMA) path rejects
  `UnrollMajorLDS` and `LdsBlockSizePerPad` outright (`:2890-2892`). So
  `TransposeLDS=1` (the MFMA path) and `TransposeLDS=-1` (which forces the
  rejected knob) are **both** illegal here, and with them the whole
  unroll-major-LDS family. The gate now refuses both values; the R47 batch's
  `TransposeLDS=-1` rows are struck and the overlay's 7 of them were pruned
  automatically (1101 -> 1094 rows). The tuning guide's knob table and its
  §9.1 census now say **unreachable** for `TransposeLDS`,
  `UnrollMajorLDS{A,B}` and `LdsBlockSizePerPad{A,B}` -- they were listed as
  virgin axes, and an unreachable axis is a different thing from an untried
  one.

  **The sweep was stopped after 75 of the 401 rows** (the operator ended it;
  74 accepted, 1 refused). Its partial result is kept in
  `gfx90c_results/analysis/deck_probe.json` in the tool's own format, so a
  later run **resumes** from row 76 rather than re-probing the first 75, and
  the refusals accumulate across a resumed sweep. The 75 rows covered the CC,
  DD, SS, HH, ZZ winner geometries and the HPA block -- every one Tensile
  accepted except the `TransposeLDS` row. **The R49 batch (the ranked
  unexplored space of the three ORANGE cells) is therefore still unprobed**:
  the deck check has not yet asked Tensile about the geometries the next run
  is aimed at.

- **2026-10-22 (5th) — the doc sweep: every stale conclusion now points at
  its correction.** The /tmp probes are gone (their capabilities are
  `oto.harness.tensile_probe` and `oto.harness.deck_probe`), and the docs
  ecosystem now carries the *reasons*, not just the numbers: the tuning
  guide's knob table says **which class** each axis with no variance is in
  (never drawn / never reached Tensile / refused by our own gate -- only the
  first kind is "open"), its §9.1 virgin-axis census carries the **status of
  every row** (closed by measurement, unreachable, or decked-and-unmeasured),
  M1 is qualified by the environment band (on the 16 identical-config cells
  the delta spans 17.5 points, so a tie there is a measurement of the
  machine), §10's sizing rule and the mutator's behaviour are current, and
  `potential_configs.md` §R2 is marked superseded beside F5.

- **2026-10-22 (4th) — the /tmp probing machinery is now the harness, and
  the launch backstop lost a rule.** The four throwaway probes written in
  `/tmp` (the Tensile derived-LDS probe, the WGM legality probe, the
  config-writing probe and the build probe) are now two tools:
  `oto.harness.tensile_probe` (ask Tensile about one config: its verdict,
  the LDS it derived, and our gate's verdict beside it) and
  `oto.harness.deck_probe` (the same, over every *unmeasured* deck row --
  the pre-run sweep, resumable, CPU-only). The probes in `/tmp` are deleted;
  their capabilities have one home each. Building them surfaced **two
  defects**: the oracle's "our gate" line was reporting the *writer's* refusal
  (the writer does not gate) instead of the launch gate's verdict, and the
  launch boundary's backstop was **missing the load-divisibility rule** -- so a
  config that violates it (Tensile: "0 valid solutions") would have been
  launched and burned a slot. The backstop now runs the loads gate too, and
  the sweep's own probe sits on a legal config (the test that probes the
  forwarding surface had to learn the GLVW/VW coupling).

  The docs ecosystem now carries the corrected conclusions rather than the
  stale ones: the tuning guide's per-family ceiling table and its M3
  mechanism are corrected (the complex families are at 80-97 % of the FMA
  roof, and the "complex throughput wall" is retired), the research brief's
  bars are stated in the client's unit, the research doc's
  "target V <= 64" rule is marked as an FP32-family rule (the measured ZZ
  counter-example refutes it for the complex families), `results.md` gains
  §16 (the corrected reading: **three** ORANGE cells, not twelve) and
  `potential_configs.md` §R42's finding F5 is marked superseded.

- **2026-10-22 (3rd) — the deck is sized for the 10 h run, and there is a
  tool that proves the new candidates build.** Two facts the previous state
  hid: the overlay's unmeasured work was **114 phases (2.5 h)**, and the
  auto-mutator contributes only ~10 candidates per iteration (the 2026-10-20
  run: 702 deck phases completed, 10 mutator phases) — so a 10-iteration
  budget was *not* a 10 h run. The **R49 batch** adds 300 rows: the ranked
  unexplored space of the three ORANGE cells, taken from the coverage map
  (the geometries the corpus has never run on ANY cell of that family, ordered
  by how well their measured neighbours scored), gate-filtered (16 candidates
  dropped as load-divisibility-illegal). The deck now carries **401 new
  phases ≈ 9 h**, plus the mutator's contribution.
  `oto.harness.deck_probe` is the missing "no bugs" gate: it puts every
  *unmeasured* deck row through Tensile's own kernel writer (the legality
  oracle) and reports the ones it refuses — the check that would have caught
  the 8 error-4 phases of the 2026-10-20 run before they cost a launch slot
  each. It is CPU-only, resumable (it records the rows it probed), and it
  never launches anything.

- **2026-10-22 (2nd) — the acceptance report carries the coverage figures.**
  A new **Problem-space coverage** section sits under the A/B table: the legal
  geometry space of every cell with the measured part painted by value, the
  never-measured part hatched, the local maxima ringed green and the local
  minima ringed red, plus a dense summary table (legal / measured /
  unexplored / % unexplored / best / peaks / traps) and the headline
  "**89 % of the legal geometries have never been run**". The numbers come from
  the coverage tool's hand-off file (`gfx90c_results/analysis/coverage/
  coverage.json`), so the report never re-derives them; the figures are linked
  relative to the report file, so the report works from the run directory too.
  The stylesheet follows the Carbon design language: the dark theme is now the
  Gray 100 token set (#161616 / #262626 / #393939 / #525252, text #f4f4f4 /
  #c6c6c6 / #8d8d8d, border #393939 / #6f6f6f), the light theme carries the
  missing semantic tokens (--layer-03, --text-placeholder, --link-primary,
  --field, --icon-primary), and the new section uses 1px borders, 0px radius,
  no shadows, 14px productive text and 2/4/8/16 spacing. Pinned by
  `tests/test_report_coverage.py`. The figures are an **expandable list by
  family**: each family is a native `<details>` group whose summary carries the
  family's own numbers ("5 cells · 24 of 205 geometries measured per cell
  (88% unexplored) · 5 peaks / 0 traps") and whose body holds the figures for
  every matrix size in that family. The per-cell share is a per-cell number --
  the legal space is the same for every cell of a family, so summing it across
  cells would divide one cell's measurement count by the family's whole space.

- **2026-10-22 — the coverage graphs: the problem space as a 2D picture.**
  `oto.harness.coverage_graph` draws, for every contract cell, the legal
  geometry space projected onto (macro-tile area x accumulators per thread),
  the measured part painted with the value it reached, the legal-but-never-
  measured part hatched, and the local maxima (green) and local minima (red)
  ringed. One SVG per cell plus an index page in
  `gfx90c_results/analysis/coverage/`, written by hand -- no dependency to
  install. What it shows: the legal space is a **band** (a big tile needs many
  accumulators per thread, a small tile few), the corpus has measured a
  **thin strip** along the middle of it, and **86-93 % of the space has never
  been visited** in every cell but ZZ (69-71 %); the traps sit *inside* the
  measured strip -- legal configurations whose measured neighbours are 3-8x
  faster -- and the peaks sit on the band's edge, which is exactly where a
  wave-quantization-limited cell wants to be. The HPA columns' attribution
  was fixed on the way (the corpus tells HHS from HSS by typecode alone, so a
  cell map keyed on the row's family showed them as 100 % unexplored).
  Pinned by `tests/test_coverage_graph.py`.

- **2026-10-21 (8th) — the legality oracle, and the three ORANGE cells
  triaged.** `oto.harness.tensile_probe` is the /tmp probing machinery
  formalised: it asks **Tensile itself** whether a config builds, prints the
  LDS it allocated, and puts our gate's verdict beside Tensile's -- so a
  legality question the CPU gates cannot answer ("does Tensile accept a
  negative WorkGroupMapping?", "how much LDS does this tile get?", "is
  TransposeLDS=1 legal without MFMA?") has one home instead of a throwaway
  script. It immediately found a **real load-gate bug**: `totalVectorsCoalesced`
  was modelled as the *coalesced* part alone (the depth, for an NT operand)
  instead of `totalElements // glvw_effective`, so the NLCA divisibility was
  checked against the wrong number; the corpus's 109 apparent false
  rejections collapsed to 0 once the model and the measurement agreed
  (calibration: 4419 agree / 140 refused / **0 MISS / 0 false rejections**).
  The contract-pattern vocabulary moved to `oto.tensile.patterns` (one
  spelling, one meaning: the problem type's transpose flags and Tensile's
  *layout* flags TLUA/TLUB are NOT the same thing -- the solution built for
  `Alik_Bjlk` carries `TransposeA: true, TransposeB: true` but `TLUA: false,
  TLUB: true`).
  `potential_configs.md` §R48 triages the three remaining ORANGE cells
  (`SS:256`, `HH:256`, `CC:192`) with a control experiment -- the *same
  binary* at a shape that fills the machine -- and shows the winners are at
  53-83 % of their own fill-and-waste bound, i.e. the cells are starved, not
  badly tuned; the reachable headroom is 1.1-1.5x and the 17 R48 rows are the
  geometries that get it. The **steal route is closed by measurement**: the
  gfx900 floor's best on the three ORANGE cells is 2.7-3.8x *below* the
  native (124.3 vs 412.1, 202.0 vs 763.4, 43.2 vs 118.2), and on the big
  cells the native already runs the floor's own config. The tuning guide's
  M3 ("the complex throughput wall") is retired -- it was the unit error --
  and the theoretical limits' ORANGE consequence is corrected.

- **2026-10-21 (7th) — the test suite is 9x faster, and the five failures
  it was carrying were a mutator that had stopped searching.** `plans/
  test_optimization.md` is executed: the dominant cost was **YAML parsing**,
  not the gates, so `oto.yamlio` (the canonical reader: libyaml when it is
  there, memoised by content) replaces every `yaml.safe_load` in `oto/`, the
  corpus reads are memoised (`ab_records.arm_record_sets` on a corpus stamp;
  `kernel_db.read_kernel_db` for the 18 MB JSON), and the three pure
  legality gates are cached by config content (`oto.tensile.gates.memo`).
  **The full suite went from 20 m 01 s with 5 failures to 2 m 10 s with 902
  passing** (1 m 27 s with `pytest -n auto`; `pytest -m preflight` is the
  36 s pre-run subset). The five failures were real defects, not stale
  tests: (a) the narrow mutation pass walked `FORWARD_KNOB_DOMAINS` in dict
  order, so the ten knobs the R45 batch added took the whole budget and
  **GlobalSplitU -- the wave-fill lever the small cells need -- was never
  drawn again**; the pass now visits the knobs in a seeded shuffle,
  round-robins their legal values, and takes at most half the budget so the
  wide (tile-donor) pass gets the rest; (b) the `nt_budget` rule was probed
  and rejected on 2026-10-18 against a *wrong* measurement (Z tt2x2 emits
  63 VGPRs, not 71) and is now **adopted** -- it is the per-thread occupancy
  limit the gate enforces, and it fires on the 8 phases that died with
  error 4 in the 2026-10-20 run; (c) `NLCA=-1` is legal and the test pinned
  the old domain. `tests/conftest.py` registers the `serial` and `preflight`
  markers and the rule that keeps a repo-tree-writing test out of a
  distributed run; `pytest.ini` records the layout; `OTO_GUARD_FILES=1`
  narrows the tree-walking guards to the changed files. The live run panel
  also gained the per-tier bars and a repaint when a phase lands.

- **2026-10-21 (6th) — the straggler list re-derived, the deck aimed at what
  is actually behind, and the coverage map.** `potential_configs.md` §R47 is
  the corrected reading of the corpus, and it changes the plan: (1) **CC and ZZ
  are at the hardware roof** (80-97 % of the FMA roof, not 20-24 %) because
  the client reports complex GEMMs at 2 flops per complex MAC and the bar was
  the BLAS-8 peak -- so the ORANGE list is 3 cells, not 12, and §R42's Class A
  and §R43's 3M/split-K routes are struck; (2) **9 of the 15 ties run the
  floor's own config** and 4 have no floor arm at all, and the 16 identical-
  config cells' deltas span **+1.1 % to +18.6 %** -- the environment band is
  17.5 points wide against a +/-5 % verdict band, and the floor arm has no
  clock telemetry, so the verdicts cannot see a win; (3) the "virgin" axes
  included three that were never varied (see the 5th entry). New tools:
  `oto.harness.coverage_map` (the legal geometry space per cell, what the
  corpus measured inside it, and the legal-but-unmeasured geometries ranked by
  their neighbours' score -- the local-minimum finder; coverage is 8-13 % of
  the legal space) and `resolve_cells --taxonomy` (what each verdict is made
  of). The R47 batch adds 55 new rows: WGM 2/3/-1/-4 (the floor's 56-CU knob
  on a 7-CU part), StaggerU=0, TransposeLDS=-1, NonTemporalC 1/2,
  MaxOccupancy 16/32, and the small cells' winner tiles with the thread tiles
  the coverage map found legal and unmeasured. The overlay now prunes the rows
  the launch gate refuses (15 of them, including the 12 SS frontier rows that
  died with error 4 in the 2026-10-20 run): 804 rows, 0 illegal.

- **2026-10-21 (5th) — three silent placebos and one contradictory knob.**
  (a) **TransposeLDS was declared forwarded but never emitted** -- the writer's
  fork surface had no entry for it, so the 5 R45 rows probing it would have
  benchmarked at the Tensile default while their manifest claimed the
  treatment ran. It is now emitted, and its legal value on this part is **-1**
  (unroll-major LDS on the NT operand, `SolutionStructs:3874-3875`): the value
  1 is the MFMA path ("TransposeLds Supports only in MatrixInstruction=1",
  `:4519-4521`) and gfx90c has no MFMA, so the gate now refuses it and the
  rows probe -1. (b) **NonTemporalC/D were never emitted either** -- the R45
  NonTemporalC rows were placebos; both are real Tensile parameters
  (`Common.py:1416-1419`, the glc/slc load flavour) and are now forwarded.
  (c) **The two spellings of LocalSplitU could disagree**: Tensile reads LSU
  from `WorkGroup[2]` and ignores the key, so a row carrying both
  (`WorkGroup: [16,16,1]` + `LocalSplitU: 2`) ran at LSU=1 while the manifest
  said LSU=2. The writer now folds the key into element [2] and the gate
  refuses a genuine contradiction. The writer's fork-surface test
  (`tests/test_writer_forwards_sweep_knobs.py`) had been failing on
  `declared-not-emitted=['TransposeLDS']` since the knob was declared.

- **2026-10-21 (4th) — the missing error-4 rule, and the frontier control
  that was never legal.** Tensile's error 4 is
  `numWorkGroupsPerCU = (65536 // NumThreads) // max(vgpr, agpr) < 1`
  (`KernelWriterAssembly.functionSuffix`): the *emitted* per-thread VGPR
  count -- accumulators **plus** operand fragments and addresses -- has to fit
  in `65536 // NumThreads`. The gate modelled the accumulators only, so it
  passed configs Tensile kills: the 8 SS frontier phases of the 2026-10-20 run
  (256x128 and 128x256 at TT 8x4/4x8 = 1024 threads, 77 VGPRs/thread against
  64 available) died with "Generating kernel source resulted in error 4" and
  the run paid for them. New rule
  (`gates/occupancy.py::_occupancy_limit_check`, estimator
  `vgpr_model.per_thread_vgpr`); the measured VGPR table is now the corpus
  **median** per (dtype, thread tile) (Z 2x2 measures 63, not 71 -- the old
  value refused a kernel Tensile builds). Gate calibration over the whole
  corpus: **4419 agree / 140 refused / 0 MISS / 0 false rejections**. The 8 SS
  "half the accumulators at the same area" control rows are removed from the
  batch: at 256x128 the only thread tile that fits 1024 threads needs more
  than 64 VGPRs/thread, so the control is impossible on this part. The HH
  control survives (H 8x4 emits 57).

- **2026-10-21 (3rd) — the "no-swizzle" arm was dead on arrival: the gate
  read Tensile's FORCE as a reject.** `SolutionStructs:3334-3336` *forces*
  `StaggerUMapping = 0` and `StaggerUStride = 0` when `StaggerU == 0`; the
  only reject is `StaggerUStride == 0` with `StaggerU != 0`. The swizzle gate
  had the rule inverted ("StaggerUStride=256 requires StaggerU>0"), so every
  `StaggerU=0` config was refused at the launch boundary as
  "forwarded-knob illegal" — **14 deck rows, 98 shape-records across the runs,
  zero measured**. The `swStaggerU0` axis (stagger off) has therefore never
  run once. Fixed in `oto.tensile.gates.occupancy._swizzle_feasible`; the
  deck and the 764-row overlay now pass the launch gate 284/284 and 764/764
  (was 270/284 and 750/764). The test that pinned the wrong behaviour
  (`tests/test_cell_attribution.py`) now pins Tensile's rule.

- **2026-10-21 (2nd) — the complex families were being scored against a 4×
  bar (accounting fix).** Tensile's client charges **2 flops per MAC for every
  dtype**, complex included (`ContractionProblem::flopCount` = `2 *
  DataTypeInfo::packing`, packing == 1 for complexSingle/complexDouble), while
  a complex MAC is *executed* as four real FMAs = 8 BLAS flops. Every
  benchmark CSV proves it: `TotalFlops == 2·M·N·K` for CC, ZZ, SS and DD
  alike. So a reported complex GFLOPS is **1/4 of its BLAS-8 value**, and
  scoring CC against the FP32 roof (1613) and ZZ against the FP64 roof (101)
  divided their real utilisation by four. The truth: **CC runs at 80-97% of
  the FMA roof and ZZ at 96-97%**, not the 20-24% the report printed. Fix:
  `oto.device.peaks.REPORTED_TO_BLAS8` (CC/ZZ = 4.0) with
  `REALISTIC_CEILINGS` / `THEORETICAL_PEAKS` derived from the BLAS-8 tables,
  so every ceiling is in the unit the measurement arrives in; pinned by
  `tests/test_complex_flop_accounting.py`. Consequences: the ORANGE list
  shrinks **from 12 cells to 3** (`SS:256`, `HH:256`, `CC:192`); CC:256 and
  every ZZ cell are GREEN; `potential_configs.md` §R42 Class A and §R43
  Routes 1-3 (3M/Karatsuba, split-K for complex) are struck as answering a
  mis-scaled bar; `gfx90c_theoretical_limits.md` gains §5.2 with the three
  independent checks (client `TotalFlops`, wall-clock vs roof time, occupancy).

- **2026-10-21 (cont.) — FractionalLoad + TransposeLDS wired.** Both were in
  `NOT_FORWARDED_KNOBS`; they are now forwarded and probed (10 rows) on the
  winner geometries. `db_knobs` gains `FractionalLoad (0,1,2)` and
  `TransposeLDS (-1,0,1)`. The remaining coupled knobs (`1LDSBuffer`,
  `DepthULdsDivisor`) need `ScheduleInnerAccuracy` forwarding and are documented
  as pending in §R44.

- **2026-10-21 — virgin-knob batch and straggler analysis.** `potential_configs.md`
  gains §R42 (five straggler classes: complex memory/occupancy, small-cell
  residency, noise ties, unmeasured frontier, virgin knobs) with per-class root
  causes and measured evidence, §R43 (8 routes: 3M Karatsuba, non-atomic
  split-K, occupancy tiling, virgin knob sweep, replication, non-temporal loads,
  WGM 2/3, AssertFree extension), §R44 (legality improvements), §R45 (a ~148-row
  candidate batch) and §R46 (5 read-only research questions). The deck now carries
  the R45 batch (LdsPad=1, NLCA=-1, StaggerUMapping=1/2, MaxOccupancy=16/32,
  NonTemporalC=1/2/3, PrefetchGlobalRead=2) — 747 candidates, 754 overlay rows,
  0 illegal. `db_knobs.FORWARD_KNOB_DOMAINS` gains NLCA=-1, PrefetchGlobalRead=2,
  MaxOccupancy, NonTemporalA-D and AssertFree {1,2,4}. `ldspad_feasible` now
  gates PrefetchGlobalRead=2 against a doubled LDS footprint. Pinned by
  `tests/test_generate_candidates.py` (gate-clean over PLAN_BATCH) and
  `tests/test_occupancy_gate.py`.

- **2026-10-20 — the preflight can check the launch set, not just the deck.**
  `check_candidates.py --deck` accepted only a bare phase list, so pointing it
  at a seed overlay crashed on the overlay's top-level `run_id`/`note` keys.
  `load_deck` now accepts both shapes, and the overnight checklist sweeps
  `phases.yaml` and the overlay together. That sweep found 3 long-stale
  gate-illegal rows still sitting in the overlay (CC 128×128 accumulator over
  budget, two patterns; SS 128×128 at LocalSplitU 2 over the LDS budget). All
  three were `skipped_illegal` in `run_20261019_180048` and are no longer
  emitted by the candidate pool, so they were pruned from the seed overlay
  (timestamped backup alongside it). Pinned by
  `tests/test_generate_candidates.py::TestDeckLoader`.

  The documented preflight also constructed the driver with `create_run=True`,
  so every invocation left an empty `started` run in the registry that the next
  launch had to clean up as interrupted. `_ends_after_preflight` now makes a
  preflight-only (or `--stage 1`) invocation read-only; the ledger records only
  real runs. Pinned by
  `tests/test_interactive_keys.py::TestPreflightNeedsNoRunDir`.

- **2026-10-20 — the corpus history is now a tool, and it corrected one stale
  frontier number.** Candidate generation kept re-deriving "has this cell, at
  this geometry, on this axis value, already been measured, and how did it
  score?" with a throwaway script. `oto/harness/corpus_census.py` is that read:
  per `family/typecode`, every structural axis value with its best seed-median
  and every geometry with its row count; `--cell FAM:side`, the same for one
  cell next to the floor's best. It groups by typecode because the HPA blocks
  (`HH/HHS`, `HH/HSS`) share family `HH` but not a geometry history, and
  `resolve_family` maps the deck's `HH_HPA`/`HS_HPA` spellings (and bare
  typecodes) onto that block, so a cell read cannot silently return an empty
  `HH` cell. It ranks on the median, never the best seed. Pinned by
  `tests/test_corpus_census.py` on a synthetic database (median basis, geometry
  collapse, placeholder/zero skip, cube-cell filter, HPA alias resolution,
  CLI/JSON paths). Registered
  in `claude.md` §2.2, `docs/developer/harness_runbook.md` (the census is question 0
  before `deck_review`) and `docs/agent_reference.md`; `oto/README.md`
  regenerated.

  The first corpus read also fixed `gfx90c_theoretical_limits.md` §5.1: its
  "measured best" column was the family best at *any* tile, not at the frontier
  tile, and the HPA entries (1399.9 / 1303.1) were mid-ladder geometries, not
  family bests. The column is now labelled accordingly with the measured HPA
  bests (1447.0 / 1441.2), and the section states that no HPA 256×128 row has
  been measured yet — the §R40 frontier deck carries it. The durable readings
  are `results.md` §15.

- **2026-10-20 — the geometry axis the deck never reached: legality, not
  preference, kept every tile small.** The 18 ties survived §R37's knob sweep
  because that sweep is about knobs; the geometry they sit on was never varied.
  Every tile above 16384 elements in the corpus (140 distinct SS geometries,
  9345 rows, 21 areas) carries ThreadTile 16×8 — 128 accumulators a thread
  against the winner's 64 — so the 30 % drop at 256×128 was a two-factor
  experiment and "big tiles are worse" was read off it. From the emitted code
  objects: SS 256×128/16×8 has 199 VGPR and 1 workgroup resident against the
  winner's 113 and 2, i.e. it lost half its residency by construction, and
  HH's large point kept its residency only because it ran at VW4/VW2 instead of
  the winner's VW8. 256×128 at VW8 was never emitted for any family, and the
  reason is the gate: Tensile's classic load structure pins `MT1 × GLVW` to the
  thread tile's accumulator count times the depth and then needs one tile side
  to be an integer multiple of the other, so a sweep of MT 64…512, ten thread
  tiles, every legal vector width and DepthU 8/16/32 through the real gate
  admits **no** tile above 16384 elements for CC, DD or ZZ and exactly one shape
  for the real families — 256×128 / 128×256 at VW2, or at VW4 under
  `AssertFree1ElementMultiple`, plus 64×512 at DU8 for the 16-bit families. The
  ceiling consequence is `gfx90c_theoretical_limits.md` §5.1 (CC's 1118.7 and
  ZZ's 98.6 bars are unreachable by geometry, and that is a bar decision, not a
  tuning failure); the deck reasoning and the four-outcome reading are
  `potential_configs.md` §R40, the finished axes are §R41. `candidate_rows`
  gains `_FRONTIER` (22 tiles), the assertion axis on 8 measured winners, a
  half-thread-tile control that separates area from register pressure, and
  `WorkGroupMapping` 2/3 on the frontier and on DD's wave-quantisation
  ties: 241 new distinct configs, ≈5 h at the
  measured 78 s per executed phase. Two deck bugs fell out: `TARGET_CELLS` was
  missing DD 768/1024/1365 and HH 4096, so three of DD's four ties and HH's
  largest could never be measured by any generated row, and
  `PATTERNS["HS_HPA"]` restated slot 2 in slot 4, halving that family's pattern
  coverage. Pinned by `tests/test_tile_frontier.py` (the exhaustive sweep, the
  named near misses, the three retired illegal tiles, and the assertion as the
  mechanism). `test_element_assertions.py`'s shipped-row guard also moves from
  `TARGET_CELLS` to each row's emitted shape list, because `_offer_row` filters
  the target sides through `_shapes_satisfying_assertions`; the invariant stays
  the same (every shape a row is measured on must satisfy its assertions) and a
  row that loses a cell to its own assertion must now say so in its note. New
  test file only, no new module, so `claude.md` §2.2 and the runbook §-list are
  unchanged; `docs/agent_reference.md` gains the test row.
- **2026-10-19 — the GPU-loss guard no longer aborts a healthy run.** The
  guard added to stop the void run (`cf18277`) counted *any* phase that wrote
  no CSV, which is the wrong signal: `run_20261018_004835` opened with three
  consecutive empty phases and `run_20261017_092909` with five, yet both went on
  to complete 400+ phases and supply the corpus's A/B. A guard that aborts on
  five of them would have killed a run whose only crime was a deck of
  unbuildable tiles. The discriminator is physical, not statistical: a phase
  that never launched the benchmark client failed at kernel generation
  ("Generating kernel source resulted in error 4") and carries a per-config
  verdict, never evidence about the device; only a phase whose client ran and
  measured nothing means the GPU is gone. The driver prints
  `loading config file .../ClientParameters.ini` immediately before launching
  the client, so that line is the test: present in every one of the 7,087
  phases that produced a measurement and in none of the 951 that did not. The
  void run's own evidence (both saved stdout tails) carried it too, including a
  phase whose log named neither `exited with code 134` nor `hipErrorNoDevice`,
  so the probe markers remain message-only. `_phase_produced_no_measurement`
  now takes the phase id and consults `_client_reached`; `_track_empty_streak`,
  `_client_aborted_at_probe` and a shared `_phase_stdout` reader follow. The
  threshold stays at 5. Pinned by `GpuLossAbortTests` (a client-reached streak
  aborts with or without probe markers; a build-failure streak does not; a lone
  result resets; a refused tile does not count; a deck shorter than the
  threshold still completes). No new module, so `claude.md` §2.2 / runbook /
  agent-reference rows are unchanged.
- **2026-10-19 — the void run is purged from every live store.** The lesson of
  `run_20261019_002432` is already frozen (the GPU-loss guard, next entry); the
  run itself was pure noise and is gone: 1111 `records` and its `runs` row
  deleted from `registry.db` (24754 records / 34 runs remain, the 1137 shared
  `phases` definitions untouched — phase rows are corpus-global, not
  run-scoped), its phantom key dropped from `analysis/kernel_db.json`, its
  486 MB run tree removed, and the top-level
  `gfx90c_results/acceptance_report.{json,html}` regenerated from the last good
  run (`run_20261018_004835`, 20 WIN / 18 TIE / 0 LOSS, "9h 3m") so the
  canonical scoreboard no longer names a run that measured nothing. Verdicts
  were whole-DB and never affected; only the report's timing/label sections had
  been polluted. A 160 KB backstop (the GetHardware abort transcript, the run's
  own report, a 412-entry manifest) is kept out of the tree at
  `gfx90c_results/purge_backup_20261019_155626/` — the run id lives on only in
  this log and in §R34, as history.
- **2026-10-19 — the virgin axes are re-decked, and one of them is closed by
  proof.** `potential_configs.md` rewrite 7 (§R34–§R39) carries the two-cause
  diagnosis of the "zero improvement" night, the honest 18-cell tie table, and
  the new deck. The deck adds `_PROBE_AXES` × `_TIE_WINNERS` in
  `oto/harness/candidate_rows.py`: four forwarded axes that no phase in the
  1137-row registry has ever carried on a winner geometry
  (`UseSgprForGRO=1` and `PrefetchLocalRead=0`, absent entirely;
  `LdsPadA/B=4`, only ever carried by the broken probe generation; and the
  `InnerUnroll=2 + UseSgprForGRO=1` combination), each on the twelve measured
  winner geometries of the tied cells — 46 rows, 0 element-multiple drops, 0
  strips, 0 refusals. `NumLoadsCoalescedA/B` was drafted as the fifth and dropped
  because the gate proved it unreachable: `gates/loads.py::_nlca_stage` needs
  NLCA to divide `numLoads`, and the winner tiles sit at `numLoads = 1` because
  GLVW saturates the 16-B cap, so NLCA>1 fails `NLCA > NumLoads` outright. Also
  recorded: `LocalSplitU` is in neither `FORWARDED_KNOBS` nor
  `NOT_FORWARDED_KNOBS`, so the two `LocalSplitU: 2` rows in `_TIE_ADAPT` are
  silent no-ops — the fourth instance of the placebo class.
- **2026-10-19 — the mutation arm can finally see the cells it exists to fix.**
  Every one of `run_20261018_004835`'s 412 candidates went to a cell that was
  already *below* its family ceiling -- 155 to SS:256, 67 to CC:192, 41 to
  ZZ:128, 39 to HH:256, 37 to DD:192 -- and the 18 cells that only TIE the gfx900
  floor got none at all. The mechanism is one line: `_mutate_cell` returned early
  when `is_below_ceiling is False`, and `is_below_ceiling` is measured against
  `REALISTIC_CEILINGS`, a measured-empirical snapshot the large cells have since
  *passed* (SS:1024 measures 1135 against a published 1118.7), so the cells that
  tie the floor are exactly the cells the arm refuses to touch. Targeting is now
  floor-relative as well: a cell earns a mutation if it is below its ceiling OR
  has not yet beaten the recalled floor, via
  `ABDeltaMixin.cells_not_beating_floor` (`agg="winner"`, so both arms are graded
  on their best per-kernel median) read once per iteration by
  `ConvergenceAgent._floor_losers`. On the live corpus that set is precisely the
  18 TIE cells -- DD/HH/HH_HPA/HS_HPA/SS/CC at 1024-4096, all within +0.1% to
  +4.6% of the floor and inside the report's +/-5% tie band. Two guards keep it
  safe: the floor is only consulted after the ceiling test, and an unreadable
  floor (no frozen reference recalled) leaves the ceiling rule exactly as it was,
  so an offline corpus cannot flood the deck. Pinned by
  `tests/test_mutation_arm.py::FloorRelativeTargetingTests` (a tie is mutated; a
  winner is settled; an unreadable floor keeps the old rule; a below-ceiling cell
  never pays for the corpus-wide scan) and
  `tests/test_ab_audit.py::TestCellsNotBeatingFloor`.
- **2026-10-19 — the overnight run can no longer burn a night on a lost GPU.**
  `run_20261019_002432` measured *nothing*: after its first phase the device
  disappeared from HIP and 413 of 414 clients aborted in
  `Tensile::Client::GetHardware` with `hipErrorNoDevice` (SIGABRT / exit 134) --
  confirmed from the systemd core dumps, whose stack is
  `__cxa_throw -> GetHardware -> main` at `client/main.cpp:273`. 9h47m of budget
  produced one phase of data, and the failure surfaced only as
  "exited with code 134" in each phase's stdout, which nothing acted on. The
  phase loop now stops itself: `PhaseMixin` counts *consecutive executed phases
  that produced no measurement* (`_phase_produced_no_measurement`) and, at
  `ABORT_AFTER_CONSECUTIVE_EMPTY = 5`, prints a diagnostic naming the probe
  abort (`_client_aborted_at_probe`, matching `exited with code 134` /
  `hipErrorNoDevice` in the phase stdout) and halts. Such a run finalizes as
  **failed** with `abort_reason` in its metadata, not as a user *interrupt*. A
  refused tile (`skipped_illegal`) is a decided outcome and never counts, so a
  legal-tile sweep is unaffected. Pinned by `GpuLossAbortTests` (streak aborts;
  a single measured phase resets the streak; a refused tile does not count; a
  deck shorter than the threshold still completes). No new module, so
  `claude.md` §2.2 / runbook / agent-reference rows are unchanged.
- **2026-10-19 — the fourteen residual literature questions folded; the second raw
  file retired.** `gfx90c_gcn5_gemm_residual_14q_caveman_full.md` (the `/caveman full`
  answer pass over the questions the first review left open) is gone. Every verdict is
  *closest-evidence-found, none gfx90c-specific*, and each now sits inline in its owner
  as a durable `[CHECK]` rationale:
  * `kernel_tuning_research.md` — **§3.4** Origami as the closest analytical GEMM
    model (its documented supported-GPU list excludes gfx900/gfx90c) and the 2025
    irregular-batched-GEMM paper as the closest mixed-tile work, plus the Tensile
    Z-order note; **§4** the AMD MI250X/CDNA2 non-temporal experiment (AMD evidence,
    but not GCN5 or GEMM) and the Tensile scoping of `StaggerU` to `TLU=0`,
    large-power-of-two K; **§8.7** the `GlobalSplitUAtomicAdd`/`StreamK`/`StreamKAtomic`
    knob names (existence ≠ performance); **§9.3** the LLVM GFX6–GFX9 VGPR-allocation
    rule (four-register units, encoded ≈ `ceil(vgprs/4)-1`) as corroboration of the
    project's granule-4 model; Sources groups extended.
  * `complex_gemm_research_brief.md` **§5** — oneMKL's illustrative first-order
    `gemm3m` componentwise error bounds, the quantitative form of the Higham caveat.
  * `knowledge_base.md` **§8.3** — AMD-specific measurement methodology (Tensile
    defaults `NumWarmups=0`/`NumBenchmarks=1`, the MI300 ~1 s / ~25 %-warmup example,
    and Primbench adaptive noise reduction), adopted as *procedure*, never as a copied
    count.
  * `potential_configs.md` **§R33** — a closing note recording that the residual pass
    turns four open `[CHECK]`s into cited "closest evidence" statements and **changes
    no route**. No new module, so `claude.md` §2.2 / runbook / agent-reference rows are
    unchanged.
- **2026-10-19 — the GCN5 GEMM literature review folded, section by section, into
  its owners; the raw file retired.** `gfx90c_gcn5_gemm_literature_caveman_full.md`
  (a `/caveman full` external pass over rasterisation/wave quantisation, complex and
  FP64 GEMM, LDS banks/padding, global-load pipeline/cache policy, split-K/Stream-K/
  persistent kernels, small-K GEMM, autotuner search-space design, measurement
  methodology, and handwritten-GCN-asm literature) is gone; each part now has an
  owner:
  * `kernel_tuning_research.md` — **§1** adds "no packed FP32 FMA
    (`V_PK_FMA_F32`)" as a hardware fact; **§3.4 (new)** is rasterisation vs wave
    quantisation (the 9-WG/7-CU tail, the transfer-only Triton/NVIDIA/cache-oblivious
    precedent, the CPU-only grid/tail ranker, mixed-tile caution); **§4** adds
    single-vs-double-buffer, `NonTemporal`, the "`StaggerU` is not a no-op until
    measured" correction, the "unforwarded knob must be verified at the generator"
    rule, and `InnerUnroll`/`DepthU` FP64 ILP; **§5** adds the Higham 3M
    numerical-stability caveat and the non-atomic split-K design; **§8.7 (new)** is
    split-K/Stream-K/persistent; **§9** adds the packed-FP32 do-not-cite row; the
    portability rule and the Sources groups are extended.
  * `complex_gemm_research_brief.md` — **§5** Higham caveat; **§8** register
    blocking under `TT0*TT1*R ≤ 128` (legality filter, not a performance proof) + the
    packed-FP32 correction; **§9** the non-atomic split-K as *new machinery*, not a
    knob; **§11 (new)** complex-double occupancy/ILP + CLBlast `6464`.
  * `tensile_tuning_context.md` **§S** — search-space size ("14–25 configs/cell is a
    small shortlist"; the ZZ 5-geometry cell is the near-duplicate failure end),
    surrogate/Bayesian recorded as *declined by `AI Rollout` policy*, and per-shape
    vs family-wide.
  * `knowledge_base.md` — **§8.3** external measurement corroboration (no universal
    iteration count or ±% band; the project's bands are its own predeclared policy);
    **§8.4** the packed-FP32 do-not-cite row.
  * `gfx90c_tuning_guide.md` **§1.2** — where the tile shape comes from (`96×96/6×6`
    is `WG×TT` arithmetic, and every ladder rung is empirical).
  * `gfx90c_theoretical_limits.md` **§3** — the square-FP32 roofline closed form
    `I = n/6`.
  * `potential_configs.md` **§R33 (new)** — the review's eight-step experiment order
    mapped onto the existing routes, with steps 4 (3M) and 7 (non-atomic split-K /
    Stream-K) marked *not reachable as candidates on this port*. It adds no route.
  * `implementation_plan.md` Completed, and this entry. Registered: no new module
    (the fold is docs-only), so `claude.md` §2.2 / runbook / agent-reference rows are
    unchanged. The review's `[CHECK]`/`[Transfer only]` labels are preserved
    verbatim in the owners.
- **2026-10-18 — the rule-calibration probe, formalised from the throwaway
  `/tmp` scripts.** `oto/harness/rule_calibration.py` applies any candidate
  rule — a `config -> Optional[bool]` predicate — to the corpus and reports the
  decision-rule confusion: false rejections on built phases (must be **0** before
  a rule lands) and empty-phase catches, by family. The `builtin_rules` registry
  ships the two shipped rules as *views* of the gate
  (`occupancy.refuses_workgroup_register_file` / `refuses_lds_reduction_buffer`,
  so a probe cannot drift from the enforcement), the generator-seam `apm2` rule,
  and the **rejected** `nt_budget` candidate (`min(256, 65536//NumThreads)` — 1
  false rejection, kept as the worked counter-example). `--rule module:attr` (or
  `path.py:attr`) probes a rule that is not in the gate yet. Live (ours):
  `workgroup_file` 0 false rejections / 40 caught, `lds_reduction` 0/13, `apm2`
  0/28, `nt_budget` 1/26. Registered in `oto/README.md`, `claude.md` §2.2/§5,
  `docs/developer/harness_runbook.md`, `docs/agent_reference.md`; the `nt_budget` finding
  folded into `kernel_tuning_research.md` §4.
- **2026-10-18 — the unparseable-tile crash fixed; `occupancy_feasible`
  decomposed.** Two robustness gaps left by the gate closure above, both pinned
  by tests:
  * **A placeholder tile no longer crashes a gate.** `loads._load_geometry`
    documented "None when unusable" but called `int()` on a non-numeric
    `MacroTile` (a `"NONE"` fork value), so `validate_tensile_loads` — and hence
    `oto.harness.gate_calibration.audit` — raised `ValueError`. It now fails closed
    to `None`, exactly as `occupancy.tile_dims` already did, and
    `gate_calibration._tile_str`/`read_phase_config` gained the matching guard so
    an unmodellable phase is *excluded* from the census rather than counted
    gate-legal. Regression: `TestUnparseableTileFailsClosed`
    and the two placeholder tests in `tests/test_gate_calibration.py`.
  * **`occupancy_feasible` split back under the 60-line rule.**
    `tests/test_function_length.py` (AC 1b) went red at 85 lines when the two new
    rules landed; they moved into `_workgroup_file_check` /
    `_lds_reduction_check`, and the model narrative into their docstrings. No
    behaviour change: the census is unchanged (3349 phases / 3217 built / 132
    refused, 0 misses, 0 false rejections) and the focused gate suite is green.

- **2026-10-18 — the legality gate is closed, and the tile axes now have
  provable ceilings.** Three calibrated rules retire every remaining native
  empty phase: the workgroup register-file rule, the `LocalSplitU` LDS-reduction
  rule, and a generator-seam refusal of the non-generative `AggressivePerfMode=2`.
  `python3 -m oto.harness.gate_calibration --population ours` goes from 53 misses
  to **0 misses, 0 false rejections** (3349 configs, 3217 built).
  * **`oto/tensile/gates/vgpr_model.py`** — new canonical readers
    `compute_bytes`, `is_hpa`, `local_split_u`, `num_threads` and the tables
    `MAX_LDS_BYTES=65536`, `COMPUTE_BYTES_PER_ELEMENT` (HPA → f32). `local_split_u`
    moved here from `loads.py` (one home), which now aliases it.
  * **`oto/tensile/gates/occupancy.py`** — `occupancy_feasible` enforces two new
    rules: `R*MT0*MT1*LSU >= 65536` (Tensile error 4; ThreadTile cancels, so this
    is a *MacroTile* bound distinct from the per-thread one — 40 empty phases, 0
    built refused) and `LSU*MT0*MT1*computeBytes > 65536` (Tensile `MaxLDS`; 13
    empty, 0 built). Both 0-false-rejection on the native *and* reference
    populations.
  * **`oto/tensile/candidate.py`** — `_non_generative_knob_rejection` refuses
    `AggressivePerfMode ∉ {0,1}` at the generator seam, beside
    `AssertSizeMultiple: [1]` (0/28 built across all seven families;
    `Components/Priority.py` dispatches only the boolean fingerprints, so
    `Priority.find` → `None` → `MAC_F32C` `TypeError`). The writer still forwards
    `AggressivePerfMode=2` verbatim — its contract test proves the forwarding —
    so this is a draw-time refusal, not a launch-boundary one.
  * **Ceilings.** The two register rules plus the LDS budget and the classic-load
    divisibility make the "*wider MacroTile*" route per-dtype: area `< 65536/R`
    (`SS/HH` 65536, `DD` 32768, `CC` 16384, `ZZ` 8192). A brute force over every CC
    tile above 8192 and every ZZ tile above 4096 finds **none legal**; the widest
    legal complex tiles are CC `128x64x8` and ZZ `64x64x8`/`128x32x8`. This retires
    the `potential_configs.md` §8.2 "legal but never generated" headroom list,
    whose four tiles all fill the register file.
  * **Deck hygiene.** `phases.yaml`'s 4 dead `ZZ trialD3` rows (128x128, 128x64)
    are replaced with the widest legal ZZ tiles `128x32x8/4x4` and `32x128x8/4x4`
    (fingerprints recomputed); `check_candidates.py --quiet` is **284 rows, 0
    illegal**. The same dead tiles lived in two further homes and are repaired
    there too: `decks.py`'s CC/ZZ wider rows move to legal tiles (CC `128x64x8`
    at 8x4/4x4 and `64x128x8/4x8`, all VW2; ZZ `128x32x8`/`32x128x8`), the
    narrow SS/HH/ZZ rows are made explicit (VW4/VW8 silently clamped to 2; the
    ZZ VW2 duplicate is unbuildable and removed), and `candidate_rows.py`'s
    `LADDER` (`CC 128x128x8/4x4`, `ZZ 128x64x8/4x2`, `ZZ 64x128x8/2x4`,
    `SS/HH 32x32x16/2x2` at VW4/VW8) and `PLAN_BATCH` (the SS
    `128x128x16/8x8` LSU-2 tie-adapt row, which needs 131072 B of reduction
    buffer) are repaired the same way. `DECISION_TRIAL_TILES` D3 is repointed
    with its rationale, and
    `tests/test_generate_candidates.py::TestEveryDeckRowIsGenerative` pins that
    no deck, ladder or batch row is refused under any contraction pattern.
  * **Tests.** `TestWorkgroupRegisterFile` and `TestLdsReductionBuffer`
    (`tests/test_occupancy_gate.py`), the APM generator-refusal and the
    no-wider-complex-tile brute force (`tests/test_knob_sweep.py`). Focused suite
    green: 130 harness tests + 111 gate/sweep/writer tests.
  * **Docs.** Rewrite 6 of `potential_configs.md` (§R24–§R32: the closed gate, the
    tie taxonomy on `run_20261018_004835` — 20 WIN / 18 TIE / 0 LOSS — the
    four-class straggler tracker, why no steal is now justified, the ceilings, the
    per-cell ledger trace, the winning kernel-type pattern, and the deck rows);
    the two mechanics promoted into `kernel_tuning_research.md` §4; the ceiling
    table added to `gfx90c_tuning_guide.md` §1.1.

- **2026-10-18 — the /tmp calibration and triage machinery formalised into the
  harness.** The two CPU-only scripts that backed the §R23 triage (the gate-vs-
  corpus agreement census and the empty-phase reason census) are now modules, so
  the next gate edit or overnight run can re-run them instead of re-deriving
  them.
  * **`oto/harness/gate_calibration.py`** — for every phase whose launch config is
    on disk, the `(built, gate-legal)` confusion across the native and replayed-
    floor populations, plus the two named work lists: **false rejections** (the
    gate refused a phase Tensile built — the decision rule requires this to be
    0 on our corpus) and **misses** (the gate allowed a phase that produced no
    measurement). The config is reconstructed from the phase's own
    `configs/phase_*.yaml` (the compiled launch truth), with the contraction
    pattern and family label recovered from their canonical homes
    (`config_writer.TRANSPOSE_MAP`, `library_parity.phase_family`) rather than a
    second copy. Reproduces the §R23 calibration exactly: native 2812 / 79 / 46
    with 0 false rejections; the floor population keeps its documented 43. (The
    2026-10-18 rules above then turn those 46 misses into correct refusals, so
    the live census is 3349 / 3217 / 132 — `results.md` §14.2.)
  * **`oto/harness/failure_triage.py`** — the empty-phase reason census (Tensile
    `reject:` lines, non-empty stderr, stdout tail, or no logs), per run and in
    aggregate: 9820 phase dirs, 944 with no non-empty CSV. Same output as the
    retired `/tmp/opencode/triage_all_runs.py`.
  * **Docs.** Both modules are wired into the harness runbook layout,
    `docs/agent_reference.md` (Key Files + Quick Start), and the `claude.md`
    §2.2 tool table; `oto/README.md` is regenerated. The durable Tensile
    mechanics behind §R23 (NumThreads/LSU, the shadowed-WorkGroup rule, the LSU
    LDS reduction, the 16-B cap check order, the APM death) are promoted into
    `kernel_tuning_research.md` §4, with §R23 pointing at that home.
  * Tests: `tests/test_gate_calibration.py` and
    `tests/test_failure_triage.py` pin the reconstruction, the confusion matrix
    and the reason-mining mechanism on synthetic corpora.
- **2026-10-17 — every failed candidate triaged; two live gate misses closed and
  the dead axes pruned out of the deck.** Three sources, all read CPU-only: the
  ledger's rejected proposals, every run directory's empty phases, and the two
  latest live runs in full. Classes and dispositions are `potential_configs.md`
  §R23.
  * **The load gate read ComplexFloat for complexDouble.** `LOAD_DTYPE_INFO["Z"]`
    held 2 registers / 8 B, so `GLVW 2 * 8 = 16 <= 16` read as legal while Tensile
    computed `2 * 16 = 32` and refused the solution — the live
    `phase_cand_zz_128_32x64x8_tt2x4_..._vw2` phase, 0 CSV. It is now 4 / 16
    (Tensile `DataType`, ComplexDouble), and the row's derived `VectorWidth`
    default follows: with `reg=4` an absent width derives 1, which is what every
    ZZ phase that actually built used. `tests/test_measurement_integrity.py` pins
    every row to Tensile's `numBytes()`, so the load gate cannot split from
    `FAMILY_BYTES_PER_ELEMENT` again.
  * **`LocalSplitU` was not in the thread count.** Tensile computes
    `NumThreads = SubGroup0 * SubGroup1 * LocalSplitU` (SolutionStructs:1964) and
    reads LSU from `WorkGroup[2]`; the gate read the tile alone, so the whole
    LSU=2 sweep looked legal. On the 24 live LSU=2 phases the corrected gate
    refuses exactly the 20 that died (`GlobalLoadVectorWidthA 2 % pv 4 != 0`,
    `Kernel Uses 131072 > 65536 bytes of LDS`) and keeps the 4 that built (CC
    `64x64x8/4x4`, HH `128x128x16/8x8`) — and 0 false rejections anywhere else in
    the corpus. The gate reads the value Tensile will receive (an explicit
    `WorkGroup` wins over the knob — see the shadowing bullet below); the sweep's
    families narrow to the two that survive.
  * **`AggressivePerfMode=2` is a dead axis, measured not guessed.** Every family
    and every tile across two runs produced 0 `.hsaco` and 0 CSV, while its mode-1
    control in the same run built 20 (one per target arch): Tensile writes the
    source and then fails to compile it. Removed from `KNOB_SWEEPS` with the
    evidence recorded in `decks.py`; deliberately not a gate, because no tile
    property predicts it.
  * **A knob shadowed by an explicit `WorkGroup`.** `LocalSplitU` is declared
    honoured (R16), but `config_writer._fork_tile` emits an explicit `WorkGroup`
    verbatim and only folds `LocalSplitU` into it when WorkGroup is absent — so
    the deck's two CC steal rows (`WorkGroup: [16,16,1]` beside `LocalSplitU: 2`)
    benchmarked at LSU 1 while their note claimed LSU 2. The gate now reads the
    *emitted* value (WorkGroup's third element wins), and the rows drop the
    explicit WorkGroup so the LSU lands.
  * **Deck hygiene.** 24 rows left `phases.yaml` (14 `swAggressivePerfMode2`, 10
    now-refused `swLocalSplitU2`), 9 left the seed overlay (the ZZ VW2
    candidate, 2 `AggressivePerfMode=2`, 6 `LocalSplitU=2`), and 8 left the
    `PLAN_BATCH` hypotheses (2 APM2, 6 LSU2). `check_candidates.py` reports 0
    illegal and coverage parity is unchanged (38/38 cells), since every removed
    row had a surviving sibling on the same tile and shape. Triaged, measured,
    and deliberately **not** gated: the LSU LDS-reduction term (needs a
    per-family destination element size) and the NumThreads-aware VGPR budget
    (needs a config-exact VGPR table; without one it false-rejects a measured
    kernel — the overreach that killed the previous VGPR model).
- **2026-10-17 — the straggler trace is formalized into the harness: `cfg_gap`
  in `resolve_cells`, the forwarding surface declared as data in `config_writer`,
  and the legality census given the device-truth domain.** The one-off `/tmp`
  trace is retired; each conclusion now has one home.
  * `resolve_cells` emits `cfg_gap` (`identical` / `near` / `retile` /
    `no-floor`) — the mechanical half of the tie taxonomy, derived from the two
    resolved configs and reported in the table, the TSV and the JSON cache. The
    reading stays in `potential_configs.md` §R17, which this corrected:
    `DD:1024` / `DD:1365` are **re-tiles** (native ties on a *different, smaller*
    tile), not the "width/DepthU step" the first reading called them.
  * `config_writer.FORWARDED_KNOBS` / `NOT_FORWARDED_KNOBS` declare the launch
    boundary's surface once, pinned to the fork helpers by
    `tests/test_writer_forwards_sweep_knobs.py`. `candidate_rows._NOT_FORWARDED_YET`
    *is* `NOT_FORWARDED_KNOBS` (4 keys → 16), so a candidate naming
    `1LDSBuffer` / `WaveSeparateGlobalRead*` / `TransposeLDS` /
    `LdsBlockSizePerPad*` is stripped and reported instead of silently
    benchmarking at the default (the §R16 placebo).
  * `db_knobs.census_domain` (global ∪ family override) now feeds
    `deck_review`'s legality census: the mutator's narrowed `forward_domain`
    saves draws, but the census must report a structural refusal even when a
    family domain drops it. This names `GlobalSplitU>1` on CC/ZZ again and fixes
    the pre-existing red
    `test_deck_review::test_structural_refusals_are_reported_with_their_rule`.
  * `tests/test_resolve_cells.py`: a drifted corpus snapshot
    (`CC:512 NumLoadsCoalescedA == 1`) was replaced by the invariant it stood in
    for — the winning phase in the latest run carries no `NLCA` in its
    `ForkParameters`, so the resolver was right and the pin was stale (the
    anti-pattern the same file's provenance test warns against).
  * Docs merge: `docs/README.md` now indexes `gfx90c_tuning_guide.md`,
    `kernel_tuning_research.md` and `complex_gemm_research_brief.md`;
    `kernel_tuning_research.md`'s dangling `archive/corpus4…` pointer is gone
    (the file was retired on the fold); `docs/agent_reference.md` gains the
    straggler-read table, the unreachable-axis stop entry, the declared
    forwarding surface and a repo-local post-run path.
- **2026-10-15 — "THE ONE LOSER" (CC:256) triaged to a candidate-pool
  sweep-order bug, not a kernel deficit; fixed at the producer.** The last
  tracked LOSS cell (CC:256, −8.7 %, `run_20261013_214649`) was not a tuning
  failure and not the documented floor-telemetry gap — that gap is
  `spoof_clock_coverage = 0.0` on *every* cell, so it distinguishes nothing and
  explains no single verdict. Root cause: `oto/harness/candidate_pool.py` sorted
  `ProblemSizes` as **strings**, yielding the lexicographic order
  `1024, 192, 2048, 256, 512`; 256³ ran immediately after the 2048³ kernel and
  its median absorbed the throttled clock (`claude.md` §2.0.3). The same CC
  `MT64x64x8/TT4x4/VW2` tile reads **54–73 GF/s** at the poisoned 256³ position
  vs 310/348 at 1024³/2048³, and **225.3** (peak) / **210.8** (median) measured
  on its own — at or above the floor's 214.9. Fix: the order is defined once in
  `oto.tensile.shape_order` (`ordered_shapes`/`shape_order_key`) and applied at
  **all three** producer sites — the wide-row build, the existing-row merge, and
  `_narrow_row_gen`'s in-place cell merge (a third site the first pass missed) —
  plus a last-mile guard in `config_writer.write_phase_config` that re-imposes the
  canonical order no matter what a producer hands it, and the same numeric key for
  the metadata/display sorts (`ab_records`, `coverage`, `resolve_cells`,
  `report_sections`). Module "Owns" notes updated. The
  defect was generator-wide — **366 of 367** generated candidate rows carried the
  scrambled order; every lexicographic-order phase in the corpus is a
  candidate-pool phase and every numeric-order phase is a deck/auto phase.
  Pinned by `tests/test_generate_candidates.py` (the `TestPoolInvariants` ordering
  invariants, the `TestShapeOrderingHelpers` helper checks, and a crafted
  `TestNarrowRowMerge` regression for the third site) and the new
  `tests/test_shape_order.py` (helper, deck, seed overlay, synthesis sweep, and a
  writer last-mile test that feeds a reversed sweep and asserts a numeric
  `ProblemSizes`). Live seed overlay regenerated
  in numeric order (`generate_candidates --prune-candidates`, mirror
  `gfx90c_results/overlays/phases.candidates.20261015_225451.overlay.yaml`; 372
  rows, 0 non-ascending). Result: `acceptance_report.json` run
  `run_20261015_041159` reads **19 WIN / 19 TIE / 0 LOSS** — CC:256 **TIE**
  (native 210.772 vs floor 214.882, −0.74 %). No verdict band or gate logic
  changed; the floor-telemetry `DECISION REQUIRED` is superseded as a closure
  path for this cell. Docs re-pointed: `results.md` §13.4, `potential_configs.md`
  F1/§2/§9-D1/§10-D1, `gfx90c_tuning_guide.md` §5/§7/§8.
- **2026-10-14 — writer forwarded every sweep knob (run-blocking fix found while
  folding corpus3).** `oto/tensile/config_writer.py::_fork_params` is the only
  path by which candidate knobs reach Tensile (`BenchmarkCommonParameters`
  carries just KernelLanguage/EdgeType/LoopTail), and it silently dropped nine
  sweep knobs — `UseSgprForGRO`, `InnerUnroll`, `NumLoadsCoalescedB`,
  `MaxOccupancy`, `AggressivePerfMode`, `FractionalLoad`, `NonTemporalA/B`,
  `AssertFree1ElementMultiple` — while `bool(PrefetchGlobalRead=2)` collapsed
  to 1 and `WorkGroup[2]` hardcoded `LocalSplitU=1`. ~200 of the 270 emitted
  sweep/trial candidates would have benchmarked Tensile defaults, including the
  AF1EM half of the D4 paired widen (without which Tensile refuses the B-side
  load at solution construction). Fixed: int forwarding for all nine, PGR as
  int, LSU via `WorkGroup[2]`. Guarded by
  `tests/test_writer_forwards_sweep_knobs.py` (19: every `KNOB_SWEEPS` value key
  round-trips into `ForkParameters`). The 310-phase manifest was emitted after
  the fix; `check_candidates.py` + `test_tensile_params.py` pass over it.
- **2026-10-14 — decision trials decked: paired CC widen swept, baseline control,
  D1/D2/D3 trial tiles.** Per the user's "add candidates as trials" instruction,
  every open decision now owns run candidates and the 10h run decides:
  `KNOB_SWEEPS` gains the CC-only paired widen (`GLVW=2` +
  `AssertFree0/1ElementMultiple=2`; `TENSILE_KNOB_DEFAULTS` gains the two AF
  defaults at 1); `generate_knob_sweep_phases(include_baseline)` + `knob_sweep
  --baseline` emits each base tile unchanged as the same-run `_base` control
  (D4); new `DECISION_TRIAL_TILES` + `generate_decision_trial_phases` +
  `knob_sweep --trials` emits D1 (CC steal geometry at 192/256), D2 (ZZ
  LDS-boundary 64x64x16), D3 (§8.2 ZZ 128x128x8 + 128x64x8). A ZZ VW2 D2
  "differentiator" was withdrawn the same day: Tensile's complexDouble
  `numBytes()` is 16, so `GLVWA x 16 > 16` and Tensile refuses the phase at
  solution construction — `consolidate_deck.dtype_bytes` already reads that
  value from Tensile and `test_consolidate.py`'s archived-ZZ gate locks the
  refusal.
  No gate or verdict logic changed. Dry-run: 246 sweep + 14 baselines + 8
  trials = 268, 0 refusals. Tests: `tests/test_knob_sweep.py` 19→26, incl.
  `test_no_emitted_candidate_passes_only_the_lenient_gate`.
  Emit: `python3 -m oto.tensile.knob_sweep --emit --baseline --trials`.
- **2026-10-14 — the harness load gate now models Tensile's shift-ptr `GLVW` rule (the 2026-09-19 "fix (pending)").**
  `loads.validate_tensile_loads` derives `GlobalLoadVectorWidth` but used to ignore
  an explicit `GlobalLoadVectorWidthA/B`, so a `GLVW=2` config passed on a
  `VectorWidth=4` tile and was then dropped by Tensile at solution construction —
  the `must be == VectorWidth … or == 1` refuses the reference rerun recorded as
  hashes `7f866dcf` / `a0edeb30`. The gate now reads the explicit value
  (`loads._glvw_for`) and applies the guard to the pv-reduced effective width
  (`SolutionStructs.py:2010`, `:4584-4596`), **conditioned** on `bufferLoad` and
  `GuaranteeNoPartialA` (`:3292`, `:4177-4183`) so the
  `AssertFree0ElementMultiple` escape hatch is not over-refused — the synthesis
  `FORWARD_KNOB_DOMAINS` explores `GLVW ∈ {1,2,4} × AssertFree0ElementMultiple ∈
  {1,2}`, and a blanket guard would have deleted a legal slice of it. Consequence:
  an unpaired `GLVW=2` is refused for CC/SS/HH/HPA and a no-op for ZZ/DD, so the
  `GlobalLoadVectorWidth` sweep row is removed (deck 12→11 sweeps, 258→244
  candidates); the one realizable widen is the CC-only pair
  `GLVW=2 + AssertFree0ElementMultiple=2` (swept as a trial later the same day —
  see the entry above). Tests:
  `tests/test_occupancy_gate.py::TestGlobalLoadVectorWidthRule` (7).
- **2026-10-10 — kernel_db auto-refresh on run completion (mutations always read fresh).**
  `kernel_db.json` is now rebuilt automatically whenever a run reaches a
  data-producing terminal status, so candidate generation / regression_matrix /
  resolve_cells never read a stale corpus. Hook is the single run-finalisation
  choke point `SQLiteRegistry.update_run_status` (covers the run loop, SIGINT,
  gfx900-reference and `--auto` driver): on `completed`/`interrupted` it calls
  `harness.kernel_db.load_kernel_db(rebuild=True)` best-effort (~4 s, logged to
  stderr, never fails the run), `skipped`/`smoke` produce no corpus so they do
  not. The hard-crash gap (SIGKILL / power loss never reaches the SIGINT
  finaliser) is covered too: `cleanup_stale_runs` — invoked at port_tensile
  startup to terminalise orphaned `started` runs — refreshes once when it
  cleans any. Opt-outs: `OTO_NO_AUTO_KERNEL_DB_REBUILD=1` (seq runners) and
  `SQLiteRegistry(..., auto_rebuild_kernel_db=False)` (tests). Cache writes are
  now atomic (temp + `os.replace`) so a concurrent reader never sees torn JSON.
  The standing "rebuild before the next grading run" item is closed:
  `kernel_db.json` now folds 12 runsets (11 native + locked floor; 21 352 rows),
  including the 2026-10-09 overnight run. Tests:
  `tests/test_registry_kernel_db_auto.py` (status semantics, stale-run cleanup,
  opt-outs, read-only guard, failure-swallow).

- **2026-10-10 — agentic harness: `harness/resolve_cells.py` formalised (repo-homed).**
  The per-cell winner resolver that generated potential_configs.md §2's evidence
  table was polished out of `/tmp/opencode/resolve_cells.py` + verdicts dump and
  integrated as `harness/resolve_cells.py` (read-only CPU tool; `--base-dir`,
  `--json/--text/--tsv`, module-style like kernel_db/regression_matrix). Additions
  over the ad-hoc version: winner-run-first phase-config resolution (winner run's
  `configs/*.yaml` → registry `phases` → any-run yaml → kernel_db row — no more
  reliance on alphabetic glob order), floor winners under the standing
  median-primary `_best` predicate, per-cell % of ceiling + % of theoretical,
  provenance metadata, and stable caches committed at
  `gfx90c_results/analysis/cells_resolved.{json,full.txt}` (byte-identical
  winners/values/knob surface to the §2 table: 6129 yamls / 8480 keys / 1113
  phases / 38 cells). `harness/__init__.py` → v1.1.0 with resolve_cells in
  `__all__`; README workflow gains a "resolve per-cell winners" step;
  `tests/test_resolve_cells.py` guards deck parity, report agreement, winner
  resolution and HPA-floor tolerance. potential_configs.md's "evidence machinery
  in /tmp until formalised" note now points at the repo-homed tool + caches.

- **2026-10-10 — potential_configs.md comprehensive rewrite: BLAS-8 complex frame, resolver-final winners, priority re-sequence.**
  The candidate-deck document was rewritten end-to-end (old 1429-line version
  archived at `archive/potential_configs.pre_rewrite_20261010.md`). Three
  load-bearing changes: **(1) Complex accounting corrected to BLAS-8.** The old
  file's "÷4 ALU wall" (CC 403.25 / ZZ 25.25, "81%/96% of wall") counted 2 flops
  per complex MAC, but Tensile's complex MAC is four real FMAs = 8 BLAS flops
  (`MAC_F32C.py`/`MAC_F64C.py`). Under BLAS-8 the honest ceilings are the FP32
  peak (CC 1613) and FP64 peak (ZZ 101); the user's CC/ZZ complaint numbers are
  correct and CC/ZZ are genuinely M3-undertuned at 20–24 % theo with ~3.5–4×
  in-deck headroom (→ SS/DD-class issue ≈ CC 1187 / ZZ 95–98) — not near a wall.
  **(2) Split-complex corrected:** reported split = (4/3)·R_real → CC ≈1513,
  ZZ ≈127–131 (was "÷3 → ≈378"). 3M wins the GEMM count (4→3) with an
  O(MN+MK+KN) combine, not the per-MAC instruction count. **(3) Winner configs
  re-resolved per cell** from the registry (`resolve_cells.py`: 6129 yamls, 8480
  keys) — 19 WIN / 18 TIE / 1 LOSS confirmed; corrections incl. CC:512 winner
  WGM4+NLCA1 (not WGM8), CC:256 native best = small MT32x32 (193.8) vs floor
  MT64x64 (212.3, sanctioned steal §7, bar ≥214), SS:512 VW4 landed (WIN +10.4),
  SS:4096 = DU16, ZZ:512/1024 = DU16+PGR=False, HH:256 = MT32x64. Corpus line
  fixed: 10 native runs + 2 locked floor runs (kernel_db 11 runsets; overnight
  20261009 folded via report verdicts only). Research anchors updated:
  `kernel_tuning_research.md` Sources now point to `complex_gemm_research_brief.md`
  (the citation anchor for §1/§8.2). `command.txt` re-sequenced: CC/ZZ M3 campaign
  first, then CC:256 steal, SS GSU, HH alternates, DD GSU, WGM probe, split-complex
  escalation. Any later doc quoting "81–96% of an ALU wall" for CC/ZZ, "WGM8 is
  the CC lever", "≈378 split", the ÷4 ceilings, or an "8 native runs" corpus is
  stale — see the rewrite's §1/§2/§3.
- **2026-10-10 — Overnight-run triage: report crash + false "HPA above ceiling".**
  Fixes from the first post-overnight triage after the DB-hooked overnight run
  (`run_20261009_205427`, ~7 h 41 m, 351 phases + 5 swizzle probes): (1) **report
  generation crash** — `_ab_records_from_csv` concatenated a `Path.glob`
  generator with a `list` when the probe_* 2_BenchmarkData scan was added
  (`TypeError` at 04:35; report now regenerates: 19 WIN / 18 TIE / 1 LOSS,
  7333 cells, 8 runs); regression test `tests/test_report_probe_glob.py`.
  (2) **false HPA anomaly** — the acceptance report showed HH_HPA/HS_HPA at
  230-246% of their FP32-rate 1613 ceiling with byte-identical bodies. Root
  cause: `_compute_family_coverage` matched `a.family == fam_lower`, but the
  Oct 9 typecode-first attribution stores the family UPPERCASE, so both HPA
  buckets fell through to the dtype fallback ('H') and reported the **packed-FP16
  HH** kernel median (2749.285, healthy at 85% of HH's real 3226 ceiling) as HPA
  "performance" — physically impossible for `v_fma_f32`. Match is now
  case-insensitive: HH_HPA 1447.0 (89.7%), HS_HPA 1441.2 (89.3%); regression
  tests `tests/test_report_family_case.py`. (3) **main-transcript capture** —
  the harness writes no main log by design (`logs/telemetry.csv` + per-phase
  logs only); `command.txt` now shows the piped invocation
  (`… --live off | tee overnight_$(date +%Y%m%d_%H%M).log`).
- **2026-10-09 (night #2) — DB-hooked mutator overhaul, Group C swizzle complete, 10+ h overnight sizing, proposal rewrite.**
  The Option H mutator overhaul landed: `db_mutator.py` hooks synthesis to
  `kernel_db.json`, emitting wide + narrow + direction mutants for every active
  (below-ceiling) cell. Mutants carry `bypass_identical_skip` (the auto-skip
  never applies to a mutation) and are novelty-checked before emission, so the
  arm never re-measures a tried config and never decays to a trickle. The
  Group C (LdsPad/Swizzle) status is now fully implemented: the backwards
  `StaggerUStride` gate in `scheduler.py` was fixed, the trio is forwarded in
  `_write_phase_config`, and 9 swizzle probe rows are in the seed overlay
  (phases.seed.overlay.yaml: 5 curated + 290 in-grid with CC/ZZ pads, PGR/PLR/GLVW/NLCA,
  SS GSU4 wave-fill, HH:256/DD:256 targets, Group C swizzle probes). The planned
  overnight run is ~15-20 h packed (iteration 1 = deck 40 + seed 295 = 335 phases
  ≈ 6.5 h; 10 iterations → ~15-20 h total). The proposal was rewritten with
  old-mutation evidence from archives, backups, registries (H addendum: decay
  171→20/iter, CC+ZZ = 93/522 mutants, 30 % wasted, zero forward knobs on mutants,
  last auto run starved CC/ZZ entirely) and the new DB mutator design replacing
  the stubby manifest-only sampler. The `proposal.md` addendum (Option H2) and
  `gfx90c_tuning_guide.md` §9/§10 have been updated accordingly. Seed overlay
  rebuilt: prune 277 → archive → regenerate 295 rows (5 curated + 290 in-grid).
- **2026-10-09 — Cross-contamination eliminated, measurement hygiene + Group C land, tuning cookbook formalized.**
  Closes `potential_configs.md` §13.2/§13.4 Groups C+D and the entire CPU-only queue
  (`implementation_plan.md`): (1) **typecode-first cell attribution** — root cause of §13.2 was
  `FAMILY_TO_DTYPE["auto"] = "S"` in `analytics.py` (the greedy 4-char `phase_auto_*` id match →
  family `'auto'` → dtype `'S'` dumped HH/CC/DD kernels into SS cells; SS:1024 reported **2142.55**
  was honest **1135.1**). Removed; `gfx90c_common.kernel_typecode()`/`family_from_kernel_name()` are
  now the single resolvers (layout-suffix-aware: `HHS_BH`→HH, never SS; `ZB_GB`→ZZ), with
  `resolve_cell_family()` (typecode wins over a contradicting stamp; HPA stamps preserved) +
  `aggregate_by_cell_typecode()`; kernel_db and both port_tensile loaders consume it per row.
  Rebuilt `kernel_db.json` (folds `run_20261008_005217`+`run_20261008_030033`; 19 608 rows):
  **0 family↔typecode disagreements, 0 HH-ish kernels in any SS cell**. 28 new tests
  (`tests/test_cell_attribution.py`). (2) **Group C forwarding** — `_write_phase_config` forwards
  LdsPadA/B, AssertFree0ElementMultiple, StaggerUStride, StoreCInUnroll behind the CPU-only
  `scheduler.ldspad_feasible` gate (padded-LDS ≤ 16 384 B/WG, StaggerUStride < DepthU·bpe,
  AF0EM ≥ 1); generator `_FORWARDED` keeps them on candidates (was silently stripped — 167/167
  reference kernels carried pads). (3) **Floor winner gate-legality proven** — `check_candidates.py
  --floor` + `--quiet`: all **30/30 per-cell floor winners pass all 4 gates natively** (whole-deck
  residue 1 464/6 855 = GLVW/VW/assembly generator-rule artifacts + 72 genuine occupancy-LDS on
  non-winners); new occupancy-margin output `wg/cu=N acc=…%.` (4) **VGPR model measurement-ratified**
  — `harness/measure_vgprs.py` reads real totals from Tensile-emitted objects (1144 scanned, 605
  mapped); invariant gate-legal ⇔ measured < 256 holds for every (dtype, TT); table in
  `scheduler.MEASURED_VGPR_BY_DTYPE`. (5) **cell_knob_diff** — `harness/cell_knob_diff.py`: 30 shared
  cells, 22 native / 8 floor; CC:256 188.1 vs 214.0 is the single outside-±2 % LOSS and the only
  sanctioned steal (Group B). (6) **auto-pool audit** — 560 `phase_auto_*` dirs; the pool wins
  13/34 cells natively (38 %), NOT marginal; legacy `phase_auto_0_{S,Z}_*` (117) wins 10 via
  typecode attribution. (7) **`--prune-candidates`** on the generator (archives then strips
  `phase_cand_*` from the seed overlay; keeps `probe_*`). (8) New canonical doc
  **`gfx90c_tuning_guide.md`** (caveman, full) formalizes the knob surface, M1–M4, measured
  patterns, floor legality, knob deltas and the overnight-run rules; acceptance bar unchanged
  (`gfx90c_theoretical_limits.md` §5). (9) **Option H APPROVED** — user decision on `proposal.md`
  §H.10: all four phases landed; go-ahead for GPU-backed mutation-arm runs (unchanged behaviours
  and `--auto` semantics per Hplan.10 stand). (10) **CC/ZZ "closed as model" closure REJECTED →
  REOPENED as deficit-worthy** (`potential_configs.md` §8.6/§13.5): the ≈20 %-of-roof "cap" did
  not survive a Tensile-suite read — the complex MAC loop is exactly 4 `v_mac_f32`
  (`KernelWriterAssembly.py:14975-14978`), so the shortfall is memory/occupancy, and all 90 gfx900
  complex ships sit on a 4-variable corner (MT/TT/VW/WGM) with GSU=1, LdsPad=0, PGR=1, GRVW=VW —
  never sampling the pad/GSU/PGR axes other families ship. Ranked resolution plan tabled
  (pads {1,2,4} → GSU>1 MultipleBuffer → PGR=0 → NLCA=3 → split-complex fallback); walls stay
  open until those probes land in a TTY run. Suite: **669 passed / 1 skipped / 27 subtests**
  (full run, 540.97 s).

- **2026-10-09 (night) — beat-the-spoof batch implemented + decked; overnight-ready pool regenerated.**
  Implements `potential_configs.md` §14.5 items 1–5 as *emitted* candidates so the overnight
  `--auto` run benchmarks every decided config in one pass. (1) **Generator fixes** — SS wide tier
  now sweeps GlobalSplitU {1,2,4} (Group A wave-fill: SS:256/512 GSU{2,4} + 64x64 alternates,
  incl. the §14.5 item-1 SS:512 VW4+GSU2 correction); **HH is pinned to GSU=1 everywhere** — the
  wide-tier `(1,2)` leak and the narrow-tier GSU neighbours are both closed (the §13.4 HH GSU2
  ban is now structural and test-locked); `TARGET_CELLS` grew **DD:256** and **HH:256** (§14.5
  Group A: DD:192/256 GSU probes, HH:256/512 64x64 alternates only). (2) **PLAN_BATCH (29 rows,
  tier `auto`, all gate-verified)** — Group C pads `LdsPadA/B ∈ {1,2,4}` on the CC `64x64x8/4x4/
  VW2/DU8` (the §8.6 S3 steal tile) and ZZ `32x32x8/2x2/VW1/DU8` winner geometries; CC steal-adapt
  variants (WGM8, WGM8+padA2, PGR=0, padA2+PGR=0, GLVW=1, all-three); PGR=0 residency rows on
  SS/HH wide tiles + ZZ winners (dual LDS+VGPR relief, §14.3); single-buffer LDS (PLR=0) reserve
  on the wide SS tile (§14.5 item 5); NLCA=3 rows on the only 3-load tile in the ladder
  (96x96x16/6x6/VW2, SS and HH). (3) **Two decided levers gate-refused → documented supersessions**
  (§8.6/§13.5 dated markers): **complex GSU>1** is not deckable — Tensile passes complex only via
  `_GlobalAccumulation` (SolutionStructs:3543-3553) and the local gate refuses it (`scheduler:
  1379-1382`), so the "MultipleBuffer wave-fill" rung-2 row is withdrawn (complex ladder is now
  pads → PGR=0 → NLCA → split-complex); **NLCA=3 needs NumLoads=3 side-wise** (128-width VW4 has
  NumLoads=1) — scoped to the 96x96 tile. Also corrected the `v_mac_f32` citation home to
  `MAC_F32C.py:55/73/90/107` (research doc §5; `KernelWriterAssembly.py:14975-14978` is the beta
  epilogue). (4) **Seed overlay rebuilt** by prune-then-regenerate (2026-10-09 16:24 mirror): 5
  curated + 290 in-grid candidates = **295 rows, all fps unique, zero GSU>1 on any banned family,
  parity + deck-legality green**; `command.txt`/guide §9-§10 updated for the new pool. (5) **6 new
  regression tests** (`TestBeatTheSpoofInvariants`: banned-GSU, SS-GSU4, pad/PGR/NLCA/WGM8 rows,
  HH/DD:256 span, knob-variant phase-id uniqueness); phase-ids now carry an fp tail so pad/PGR/NLCA
  variants can never collide. `kernel_tuning_research.md` (background subagent) landed in the docs
  ecosystem (§14.6 pointers + §8.6 citation already aligned). Suite: **675 passed / 1 skipped /
  27 subtests** (full run, 720.67 s).

- **2026-10-09 (evening) — beat-the-spoof analysis pass: verdict anatomy, occupancy audit, all-around plan.**
  (1) **Native-vs-floor verdict anatomy** (`harness/cell_knob_diff.py` on the rebuild): the |Δ| ≤ 2 %
  band tally is **17 native / 8 tie / 5 loss** — SS:512 (+3.8), SS:1365 (+3.2), HH:1024 (+4.0),
  HH:2048 (+6.6), CC:256 (+13.8). Dissected into four classes (`potential_configs.md` §14.1/§14.2):
  two clock artifacts (SS:1365, HH:1024 — native medians from the 1.175 GHz-suppressed
  `run_20261008_030033`, nothing clock-normalized), one same-kernel cross-run noise row (HH:2048,
  byte-identical kernel both arms), one suboptimal VW2 pick (SS:512 vs floor VW4 on the same tile),
  and one real direction+residency deficit (CC:256 — the sanctioned steal). The old §13.6 "single
  outside-band LOSS" phrase gets a dated supersession marker. (2) **The "occupancy ≤3" investigation**
  (**new `harness/occupancy_bounds.py`**): 25/34 cells genuinely sit at ≤3 resident wg/CU (median 3,
  min 2, max 10; 8–24 of 40 wave slots) — physical, not a model bug; **VGPR file binds 21 cells**,
  LDS 13. The spoof floor is equally non-resident (26/30 ≤3), so occupancy is *not* where the floor
  wins; and a single-buffer LDS probe barely moves the count (VGPR becomes the wall for 33/34 cells)
  → **residency levers must free VGPRs (GSU > PGR=0/GLVW ↓ > TT ↓ > LDS-side)**, which re-derives
  the M2 wave-fill agenda with numbers behind it. (3) **All-around plan** (`potential_configs.md`
  §14.5): clock-pinned head-to-head re-measurement as the M4 prerequisite, SS:512 VW4@same-tile+GSU2,
  Group A wave-fill (SS/HH/DD small squares), the CC:256 gfx900→gfx90c steal-adapt with adaptation
  documentation (tile ports; LdsPadA=2 + WGM8/4 + GSU2 + PGR0), and the ranked Group C probe order.
  (4) **Web-research pass** landed `kernel_tuning_research.md` (GCN5/gfx90c model, LDS bank math,
  occupancy theory, Tensile knobs, complex-GEMM incl. split-complex, SOTA cross-SKU porting — all
  URL-cited), cross-referenced from §14.6.

- **2026-10-08 — overnight-run deep triage: why the ceiling "didn't move" (potential_configs.md §13).**
  `run_20261008_030033` (6h 9m, PROVISIONAL FLOOR, 22 WIN / 15 TIE / 1 LOSS) dissected per
  dtype/family/shape against the locked gfx900 floor, `kernel_db.json`, and the occupancy model.
  Finding: ties are mostly **walls, not tuning failures** — (M1) SS/HH/DD/HPA large-squares sit at
  the realistic ceilings (SS 768+ 93–102 % of 1118.7; HH 1024+ 96–108 % of 2461; DD 768+ 90–98 %
  of 98.6; HPA *above* its derived bar), native and spoof within ±5 % (SS:768 -0.5 %, DD:2048
  +0.4 %, H:4096 +0.1 %); (M2) the 192/256/512 small cells are **wave-quantization-starved**
  (36–64 waves on 28 SIMDs = 13–23 % residency — real headroom via GSU/wave-fill, e.g. SS:256 412
  vs 1135@1024 is exactly the residency gap); (M3) CC/ZZ cap at **290–318 / 21–24 GFlops at
  91–1463 % residency** — a Tensile complex-codegen wall (4–6 instr/MAC, 2× reg footprint, 2–4×
  LDS bank-conflict amplification on 8/16-B elements) that the gfx900 ships hit too, so no
  tile/pattern mutation crosses it: the only lever with a mechanism is `LdsPadA/B` + swizzle, the
  knobs `_write_phase_config` currently strips silently — flagged as Group C candidate;
  (M4) the run measured at **1.175 GHz vs 1.8 GHz reference (≈1.53× suppressed,
  native_clock_coverage 0.53)** so its absolute numbers are flat by construction and its verdict
  deltas vs the full-clock floor are not comparable (its wins are within-run-relative only).
  §13.2 exposes report-level contamination: 4 S cells "won" by `phase_*_hh_*` phases
  (honest SS = ties at the ~1100 plateau), `H 512`/`H 256` values referenced from non-matching
  phases and from the two runs missing from `kernel_db.json` (fold via `--rebuild`), giving a
  fair re-tally ≈ **18 WIN / 19 TIE / 1 LOSS** (CC:256 -11.4 % the sole honest loss). §13.3
  pattern wins (NT everywhere; VW pinned to the 16-B load cap; WGM8 is a real CC lever;
  GSU unused in all winners). §13.4 candidate plan: Group A wave-fill (SS/HH/DD 192–512 via
  GSU{2,4}), Group B CC:256 = sanctioned spoof-steal (`Ailk_Bjlk`+WGM4/8, wave-fill alternates),
  Group C LdsPad/Swizzle forwarding + legality gate for CC/ZZ, Group D hygiene (kernel_db
  rebuild, typecode-filtered cell derivation, clock-normalisation). §13.5 records the CC/ZZ
  ceiling-model caveat (derived ceilings don't subtract the complex codegen cap → permanent
  orange regardless of deck). Doc-only change; no code touched.

- **2026-10-08 — Generated seed candidate pool (proposal D4) implemented + triage of the short run.**
  Triage of `run_20261008_005217` (~22 min, 16 phases, 0 proposals): the executed command was the
  manual one-shot `--stage 3` (`command.txt:19`), not the overnight `--auto` loop (`command.txt:53`);
  the auto arm also collapses on iteration 1 with "No valid mutations generated, stopping" — the
  native arm had no novel candidates left. Root gap: not enough proposals, not the deck. Fix =
  `harness/generate_candidates.py`, which emits a **287-row config→shapes candidate pool**
  (one row per config; fp is shape-independent and a row carries ALL of its family's in-grid target
  cells, matching deck semantics): wide (252, ladder tiles × patterns × DepthU 8/16 × GSU × WGM 4),
  narrow (24, 1-knob neighbours of each cell's deck winner, merged onto the wide row that already
  measures the fp), auto (2 explicit evidence rows N6/N7 — N6 fingerprint-identical to a wide row),
  probe (10, off-grid SS 32/64/128 + DD 128 at forced DepthU 4, `graded: false`, structurally disjoint).
  Parity-safe placement: only the **277 in-grid rows** land in `phases.seed.overlay.yaml` (282 total
  with N1–N5); the 10 probes live in the timestamped mirror only (`--with-probes` opts them into the
  seed and breaks `test_seed_only_extends_within_grid` until the rule is amended). Verified CPU-side:
  unique phase_ids + fps, zero deck/curated-seed fp collisions, full cell coverage, per-row dtype/label/
  ScheduleName/NumBenchmarks, and all 277 rows pass the real launch-boundary `_write_phase_config`
  (both CPU gates, 0 refusals). `tests/test_generate_candidates.py` (14) + `tests/test_library_parity.py`
  (17) green. Mirror: `gfx90c_results/overlays/phases.candidates.20261008_024733.overlay.yaml`.
  Overnight budget note: deck (40) + seed (282) measure once per run before the loop mutates.
  Open: ceiling model still %-of-roof for CC/ZZ (§8.6); the three analytics feed gaps
  (`probe_*` globs ×3, dtype-from-config, `_write_phase_config` forwarding of LdsPadA/B,
  AssertFree0ElementMultiple, StaggerUStride, StoreCInUnroll) are still unimplemented.

- **2026-10-08 — Coverage-parity rule formalised + ad-hoc /tmp machinery integrated as `harness/`.**
  The produced `tensilelibrary.dat` must map EXACTLY to the shipped gfx900 grid in (shape, dtype)
  cells — no contraction, no extension — canonicalised once in `knowledge_base.md` §6.1, with
  mechanical enforcement only (the rule has one home): `check_library_parity.py` CLI (deck + seed +
  `--run-id` overlay vs `gfx90c_common.shipped_cells()`, exit 1 on divergence), a `run_preflight`
  parity verdict, a `consolidate.py all --commit` refusal gate, and `tests/test_library_parity.py`
  (17 passed) pinning the committed deck + seed overlay to 38/38. The measurement machinery built
  ad-hoc in `/tmp` now lives repo-homed: `harness/kernel_db.py` + `harness/regression_matrix.py`
  (median basis, per-family 38-cell grid; `kernel_db.json` rebuild verifiably identical to the §12
  snapshot). §12/doc numbers re-based to the per-family grid: **9 losses vs floor (8/9 config
  identical, S:512 the only real knob diff), 16 wins, 13 ties**, and **one material median
  finding** — HH_HPA:4096's stranded iteration-9 overlay winner (`phase_auto_1_hh_hpa_2048x2048x2048_4`,
  −4.0% at the median) to be shipped as probe N7. Verified vs the full deck: parity CLI PASS 38/38,
  `kernel_db.json` row-for-row identical to the published §12 corpus.
- **2026-10-07 — D1 deck bootstrap implemented; all-run regression list = 0 material median regressions (dtype view; 1 per-family carry-over, in the body).**
  The 11 provenance winners from §8.4 + the seed overlay's proven rows (CC 192/256, HH_HPA 512,
  HS_HPA 512, and the `phase_auto_{0,2}_*` rows) are appended to `phases.yaml` — deck now **40 rows** —
  each with `fp = fingerprint_config(config)` and `contraction_pattern`, so they re-benchmark once
  next run (the measure-once bootstrap that makes the next overnight productive instead of the
  run-20261007-012721 silent no-op: 29 records, all `identical_fp_already_passed`, 0 proposals →
  empty harvest → "No valid mutations generated, stopping"). The seed overlay is trimmed from 16 rows
  to **5 probes (N1–N5)**; the iteration-9 tail (23 proposals, 21 accepted, stranded in
  `phases.run_20261006_122020.overlay.yaml`) stays accounted under decision D2, not lost.
  `TestDeckIsVerbatim` now exempts D1 rows (`phase_auto_*`) from byte-verbatim and pins them on
  `fp == fingerprint_config(config)` + `contraction_pattern`. Verified: `test_consolidate` 20 passed,
  `test_phase1_integration` 57 passed; full suite 603 passed/1 skipped/27 subtests (as documented).

  **Programmatic all-run regression list** (`gfx90c_results/analysis/regression_matrix.json`, §12 of
  `potential_configs.md`, regenerated by the repo-homed `harness/` tools): per-cell (family, shape) of the
  shipped grid (38 cells) deck-issued best-median vs all-time best-median across every native run + the
  gfx900 floor. Result: **38 cells, 1 material median finding** — the deck ships the median-best kernel for
  every cell except **HH_HPA:4096**, where the stranded iteration-9 overlay candidate
  `phase_auto_1_hh_hpa_2048x2048x2048_4` runs −4.0% above the shipped kernel at the median (1411 vs 1355)
  and should be shipped as a D-row (probe N7); the §8.4 reuse-loss hole is closed bar that one carry-over.
  Residual vs floor (>2%, median): **C:256 (−12.1%), H:1024 (−7.0%), S:1365 (−6.9%), H:2048 (−6.2%),
  S:768 (−4.4%), S:1000 (−4.2%), C:1024 (−3.9%), S:512 (−3.7%), S:2048 (−2.0%)** — of which **8/9
  benchmark the identical config the deck already ships** (the residual is cross-run variance, not a
  missing knob) and only **S:512** differs (deck VW2 771.9 vs floor **VW4 801.6**), the one knobs-level
  target on the board.
  H:256 "LOSS" reconciled as a basis flip: floor `MT128x128/8x8/VW2/DU8` best-seed 303.6 has median
  171.3 (below the deck's 206.5); by median the deck wins +2.5%, by tail it "loses −31%". Occupancy:
  45/45 deck+seed rows pass `occupancy_feasible` (wg/CU 512–8192, register-file metric).
- **2026-10-07 — Persistent seed overlay (D2b) lands; mutation arm no longer self-cancels.**
  A 2026-10-07 auto run executed *zero* phases: the deck's 29 rows are all `identical_fp_already_passed`,
  the mutation arm only harvests winners from the current run's CSVs, so 0 measurements → empty
  harvest → no mutations → stop at iteration 1. The root cause is the skip/harvest contract, not a
  bug, but it meant the arm could never bootstrap a deck it had already passed. Fix: a static,
  run-independent seed overlay (`gfx90c_results/overlays/phases.seed.overlay.yaml`) merged by
  `load_phases_manifest` every run, tagged `origin=seed_overlay`/`overlay_run_id=seed`, with
  `phases.yaml` provably untouched. It carries 16 rows — the 11 measured all-time winners (with
  their full shape grids) plus probes N1–N5 — so a fresh run re-benchmarks each proven winner once
  against the live GPU instead of skipping it. Two planned probes were dropped during validation:
  they were fingerprint-identical to existing winners (same MT/tt/vw/du, different shapes) and
  added no signal. `run_phases` gives seed rows *measure-once-per-run* semantics: `has_run_benchmarked(run_id, fp)`
  (new on `registry`, and the identical-fp method whose body had been accidentally deleted during
  scoping was restored) gates the iteration-1 bypass off for the rest of the run, so a static seed
  never re-fires every iteration — verified 16/16 + curated each executed exactly once across 3
  iterations in a stubbed-executor harness. Four tests added; full suite 585 passed, 1 skipped,
  27 subtests.
- **2026-10-06 — `legal_slow` is reference-derived, and the Phase-4 legal rate hit 100%.**
  The legality verdict is now measured the way the gfx900/spoof reference actually ran:
  `ab_audit.cell_deltas()` exposes the spoiled reference median per cell, and
  `coverage.reference_thresholds()` (cached, re-entrancy-guarded) computes the band once and
  gives every cell a bar of `reference_median * (1 - band/100)`. `classify_outcome` reports
  `legal_slow` only when **every** measured cell in a sweep is below its bar (ties are not
  slowness; one competitive shape rescues a sweep), unmatched cells are never slow, and
  zero-throughput is `non_functional`, not slow. Two implementation details that mattered:
  the per-cell bars must be built lazily (the band itself can only come from
  `ConvergenceAgent.band()`, see the Phase-4 entry), and the dtype must be resolved from the
  phase id for the cell keys — an unresolved dtype silently mutes the whole verdict.
  `tests/test_legal_slow.py` pins it, 28 tests.

  Second finding: **the registry WAL is part of the ledger.** Copying `registry.db` alone
  after an un-checkpointed write loses the newest rows (`-wal` must travel, or
  `PRAGMA wal_checkpoint(TRUNCATE)` first) — demonstrated by `tests/test_ledger_durability.py`
  (9 tests) with an `early`/`late` write split across a copy+restore.

  Third: **an 88% legal rate was hiding a structural bug, and the fix is manifest reading,
  not a reject-set model.** The sampler crossed `DepthU`/`GlobalSplitU` onto incompatible
  tiles. The shipped manifest stores DepthU as the K component of the MacroTile
  (`128x32x16` *is* "MacroTile 128x32, DepthU 16"), so `DepthU` now rides with the `tile`
  group, and `legality.cooccurrence_check` rejects every cross-group knob pair that never
  ships together (read off the manifest, cached, deliberately *not* the occupancy/assembly
  predicates — those still reject shipped configs: 31/135 HS_HPA, 19/169 SS). Measured:
  legal rate 88% (176/200, HS_HPA 0%, HH_HPA entirely declining) → **100% (232/232), all
  seven families proposing, zero false drops.** The gate cannot reject a shipped config —
  a shipped solution co-occurs with itself.

  The overnight command now exists: `python3 port_tensile.py --auto --yes --budget 10
  --mutation-budget 2 --live off` (appended to `command.txt`).

- **2026-10-06** — **Option H Phase 4 landed: coverage-guided synthesis, graded candidates.**
  New `synthesis.py`, plus the agent/mutator wiring to use it. `Hplan.6`'s four items: coverage
  state now directs which knob groups a draw may touch; the lattice remains as a reported
  fallback; candidates carry the family's shape sweep so a mutant is gradable at all
  (`Hplan.1` item 5); and `ThreadTile`/`WorkGroup` are re-derived from `MacroTile`.

  Two findings worth keeping. First, `Hplan.6` item 2 ("extend beyond the lattice's six
  knobs") was **already satisfied by Phase 2**, and is now exhausted rather than merely
  satisfied: all eight structural knobs the shipped solutions encode are covered. The ninth
  parsed knob, `grvw`, is excluded on purpose — it is not a Tensile parameter, and
  `BenchmarkStructs` calls `printExit()` on unrecognised names. A knob invented to look like
  progress would have aborted parameter filling instead.

  Second, and more important: **the acceptance band cannot be computed in
  `ConvergenceAgent.__init__`.** `ab_audit.arm_record_sets` builds an agent to manage phases,
  and `coverage.measured_band_pct` calls `arm_record_sets`, so doing it at construction time is
  `measured_band_pct → agent → agent → …` and terminates only by exhausting the stack. This
  presented as `TestMeasuredBand` *hanging* rather than failing, and it cost real time to
  diagnose — the traceback was the only evidence. It is now `ConvergenceAgent.band()`,
  resolved lazily, at most once, with a re-entrancy guard, and `BandResolutionTests` pins it.
  The related question of "is 5.0 a real measurement?" has a clean answer: it is
  `TIE_BAND_PCT`, the documented shipped floor, chosen by `measured_band`'s `max(...)`, so on
  an empty corpus the band is the floor and says so via `band_source`.

  Two latent bugs surfaced by the new tests and fixed: `reconcile_tile` returned early when
  `ThreadTile` or `WorkGroup` was **missing** — precisely the case it exists to solve — and an
  unsolved dimension rendered as the literal string `"None"`, which Tensile rejects at
  parameter-parse time rather than at our own check.

  Design choice worth recording: **the ledger's single `shape` column keeps the cell identity,
  and the sweep lives in phase data.** Coverage joins on `(family, shape)`, so storing the
  sweep's first shape would re-file the candidate into a different cell and quietly corrupt
  every coverage join.

- **2026-10-06** — **Option H Phase 1 integration closed: the ledger now actually runs.**
  Phase 1 shipped every piece of Hplan.3 and reached a run with none of them wired. Each gap
  failed silently, which is why none of it was visible from the tests: the per-run overlay was
  written and never merged into the deck, so candidates were emitted, recorded, and never
  scheduled; `run_id` was dropped on emission; the proposal row and its phase were two commits,
  so a crash between them left a permanently-`pending` candidate whose `n` never grows and
  which is therefore re-routed to `replicate` on every later pass, indistinguishable from
  genuine instability; `resolve_phase_dir` was never called by the driver, so the ledger only
  ever accumulated `pending` rows; `WinnerFreq` was parsed by a private CSV reader whose failure
  mode is zeros, which reads as "no kernel won"; the negative cache was process-local, so every
  restart reported a saturated neighbourhood as untouched — it switched off exactly when needed;
  and `skip_mutation_arm()` was computed on every emission and then ignored by the loop that
  performs the skip.

  `load_phases_manifest` now merges this run's overlay (tagged `origin: overlay`), keyed on the
  active run and suppressed for an explicit deck so `--gfx900-reference`'s spoof floor can never
  absorb native candidates. Proposal and phase are inserted in one transaction
  (`emit_proposal_with_phase`). `run_phases` calls the outcome write-back for phases that
  actually launched, so a phase that never ran is not classified as `non_functional` for having
  produced no output. WinnerFreq is read through `analytics.read_column`/`winner_freq` — the
  single owner of Tensile column parsing — and persisted to a new append-only
  `proposal_observations` table, written before the verdict so a crash leaves recoverable
  evidence rather than a decision with no basis. WinnerFreq lives outside the `proposals` row
  deliberately: evidence is re-observable, verdicts are decided once, and columns there would
  invite overwriting the basis of an already-made decision. The negative cache is rebuilt from
  the ledger's resolution order at construction, because `consecutive` is a claim about
  sequence. The identical-fp bypass is scoped to overlay phases only, so it cannot re-benchmark
  settled curated phases.

  Also fixed: `SQLiteRegistry.__init__` ran the additive schema migration unconditionally, so
  every `ab_audit` run rewrote the live floor registry's bytes — schema only, no row touched,
  but a report had changed its own subject. `SQLiteRegistry(base, read_only=True)` skips the
  migration and every mutating method raises `PermissionError`; the audit now reads read-only.
  New `tests/test_phase1_integration.py` (53 cases) drives the driver's loop rather than the
  helpers, since testing the helpers in isolation passes even when the loop calls neither.

- **2026-10-05** — **Option H Phase 3 landed: cell coverage, three distinct states, and LCB
  parent selection.** New `coverage.py` reports per `(family, shape)` evidence (distinct
  fingerprints, `min_n`, median, spread) and classifies each cell as `explore`,
  `replicate` or `retired`. `agent.harvest` now picks a parent by **lower confidence
  bound** instead of raw winner, which closes the path by which a noise-level win becomes
  the parent of the next batch: a config whose median is high because one seed landed well
  now ranks below a merely-good one. `CellAnalytics` carries its seeds (an LCB is not
  recoverable from a median, a CV and a count), `ab_audit.py` prints `n`, spread and the
  novel/replicate split, and `registry.all_proposals` exposes the ordered ledger.

  The states are kept deliberately distinct: retirement is only reachable once decided
  evidence exists, so "never tried" is never recorded as "tried and failed" (§H.1.2a), and
  `legal_rejected` does not retire a cell because a rejected proposal never ran. `min_n` is
  the *worst* measured config in a cell rather than the mean, since averaging that away is
  how thin evidence becomes a verdict. The acceptance band is read from
  `ab_audit.reproducible_band` and returns `None` when it cannot be measured, rather than
  falling back to a literal — the same failure mode as the retracted `GFlops` figure. A
  single sample degrades the bound to its median instead of claiming precision; thin
  evidence is reported as thin. `parent_by="median"` stays reachable and
  `selected_by_lcb` / `parent_by` / `parent_score` are recorded per winner so the two
  policies stay comparable on the same data.

  **Defect found and fixed during the phase.** `coverage.measured_band_pct()` never
  actually read a band: it called `ab_audit.reproducible_band()` with one argument for
  a two-argument function, and a bare `except Exception` converted the `TypeError`
  into `None`. Every cell therefore evaluated with no band at all, while the plan and
  changelog asserted the band was measured from the corpus. `ab_audit` now exposes
  `arm_record_sets()` and `measured_band()` — the exact two calls `audit()` makes —
  so coverage reads one canonical band, the audit passes its band into the coverage
  report instead of recursing into itself, and the two cannot disagree. Measured on
  the current corpus the band is **18.29%**, against a shipped floor of 5%. The test
  that missed it (`assertTrue(value is None or value > 0)`) passed for a function
  that always raises; it is replaced by four assertions, all of which fail when the
  read is stubbed back to `None`. Also added explicit `target_cells`, so a cell that
  was targeted but never proposed for is reported as `explore` rather than vanishing.

- **2026-10-05** — **Option H Phase 2 landed: manifest-derived legality prior, measured live
  at 35.7% -> 85.3% legal.** New `legality.py` replaces the ≤2-knob lattice in
  `agent.mutate_and_feed` with a prior that draws knob values only from what Tensile ships
  for that family, so the reject classes are never proposed. Measured on the same 29 curated
  parents, same process, same `validate_config`: lattice 417/1169 legal, prior 198/232. The
  lattice figure reproduces the D3 table when re-run, which is the cross-check that both
  arms share one reject model. Hard walls encode the half `VectorWidth` floor and the
  no-schedule MacroTile case; `validate_config` stays an assertion per Hplan.4 step 4, so
  the residual (occupancy, and load divisibility on the full problem instance) is recorded
  `legal_rejected` rather than searched away. `tensile_library` gained public
  `shipped_kernel_config` / `shipped_kernel_knobs` wrappers and an `AF0EM` field so the prior
  reads solution names through the single existing parser; `_config_from_kernel` is unchanged
  so the pinned reference build is untouched.

  Three corrections came out of implementing it, and none of them are confirmations:
  (a) the audit's `A_half_VW1_assembly` is two conditions in different places, and the GSU
  half is not enforceable from our config surface — a first cut that modelled it produced 90
  false rejections on shipped HS_HPA `GlobalSplitU` 2/3/5/7 vectors, so it is now recorded in
  `legality.DEFERRED_RULES` with its reason rather than enforced wrongly; (b) the half
  `VectorWidth` wall was **dead on arrival** because `EnableMatrixInstruction` tests
  `len(ThreadTile) == 2` while our configs carry ThreadTile as the string `"8x4"` — every
  candidate read as undetermined and the sweep reported a perfect 100% accepted, which is
  how the bug surfaced; (c) GlobalLoadVectorWidth is a function of MacroTile, so schedule and
  loads had to become one atomic group, and the base had to be a complete shipped vector
  rather than the partial deck config.

- **2026-10-05** — **Option H Phase 1 landed: append-only `proposals` ledger, outcome
  classification, and a mutation arm that stops writing to `phases.yaml`.** New `mutator.py`
  (classifier, novelty, negative cache, per-run overlay); `registry.py` gains the `proposals`
  table plus `record_proposal` / `resolve_proposal` / `is_novel` / `coverage_view`, created
  additively so an existing registry picks it up on next open without rewriting a row;
  `agent.mutate_and_feed` now emits to a per-run overlay (`gfx90c_results/overlays/`) and
  refuses to re-propose a known fingerprint, which is the first time D2 and D4 are actually
  closed rather than described. `analytics.count_benchmark_rows` was added because the
  classifier must distinguish "rows that produced nothing" from "no rows" and the value-loader
  drops non-positive rows by design — CSV shape now has one owner, as does CSV values.
  Two guards are load-bearing and tested: `ConvergenceAgent.skip_mutation_arm()` returns True
  when the ledger is missing **or** when it exists without an outcome signal, so the
  identical-fp bypass cannot be unlocked by a novelty-only ledger (Hplan.3 steps 8 and 11).
  `resolve_proposal` advances `pending → terminal` exactly once and silently no-ops after,
  and the registry exposes no delete method, so append-only holds by interface rather than by
  caller discipline. `scheduler.mutate_winner` is unchanged — Phase 1 fixes the loop's memory,
  not its generator. No GPU work, no full Tensile benchmark, `phases.yaml` untouched, and the
  live `registry.db` byte-identical after the run (verified by sha256). Suite: 317 tests,
  1 skipped, exit 0.

- **2026-10-05** — **RETRACTED: the "mutants produced zero GFlops" finding was an artefact
  of the wrong CSV column.** `proposal.md` §H.1.2a reported 2,480 mutant benchmark rows with
  0 non-zero GFLOPs, and the whole Option H priority list was ordered on it. The count was
  read from the column *headed* `GFlops`, which in these CSVs is a **problem index**, not a
  throughput — it reads `0,1,2,3` across a four-shape file and `0` in any single-shape file.
  Real throughput is in the trailing `Cijk_…` kernel column, which is what the canonical
  loader `analytics.load_benchmark_csv` reads. Re-measured through that loader the sign
  flips: **2,960 rows, 2,960 non-zero, 370 of 374 dirs productive.** The mutants were never
  broken. What is true, and what D5 already said, is that they are **ungraded**: keying both
  populations by (kernel class, shape) leaves exactly **one** like-for-like cell out of 14,
  and in that cell the mutants are *better* (6.89 vs 4.36 median). Two defects survive —
  outcome is never recorded (D6) and every mutant is single-shape (D5) — and the second is
  now co-equal with the first, since an unmeasurable result is not a search result.
  **Why a same-run positive control did not catch it:** the control (`phase_zz_*`) is
  non-zero under *both* readings, so the control passed while the measurement was wrong.
  Lesson recorded in `proposal.md` §H.8 and §H.11: prefer the canonical loader over a column
  name, and key comparative claims by (class, shape), not raw yield. Every affected claim in
  §H.0, §H.1.2a, D3/D6, §H.3, §H.3.4, §H.3.8, §H.4, §H.7.10-11, §H.8 and §H.11 has been
  corrected in place; the original figures are quoted only inside the correction notices.

- **2026-10-05** — **`--auto` cannot express "no mutations".** Found while formalising
  the Option H mutator plan. Three independent traps: `--mutation-budget 0` still emits
  single-knob mutants (the budget gates only the two-knob block in
  `scheduler.mutate_winner`); `--budget 1` still harvests and mutates, because
  `run_auto` calls `mutate_and_feed` before incrementing the iteration counter
  (`port_tensile.py`), so a single-iteration run appends candidates to the curated
  `phases.yaml`; and `--stage` gates only the non-`--auto` branch. The mutation-free
  path is therefore to omit `--auto` and use the plain Stage-3 route, which is what
  `command.txt` now records. **Resolution:** the user confirmed omitting `--auto` is the
  intended route, so the proposed `--mutation-budget 0` = "emit nothing" fix is
  **withdrawn** — `--auto` semantics stay as they are. The overpromising flag text is
  still wrong and Option H fixes the underlying width problem in `scheduler.mutate_winner`
  by construction rather than by flag (`implementation_plan.md` §Option H, `Hplan.10`).

- **2026-10-05** — **`s`/`e`/`q` were dead while phases were skipped, and stdin had
  two competing readers.** A phase that policy skips (identical `fp` already
  passed) does no GPU work, and that code path polled no keys at all — so a
  re-run or `--resume` of an already-passed deck ignored `q` completely until
  some phase actually launched, which for a fully-skipped deck is never. The
  keys are documented as run-wide, so the gap was a contract violation, not a
  missing feature. Root cause was structural: the `select`+`read(1)` poll was
  copy-pasted into the cooldown latch and the Tensile wait loop and simply
  omitted from the third context.
  - stdin now has a single owner, `TensileDriver._read_key()`, used by all three
    call sites. Two pollers on one fd race for the same byte, so the keys could
    mean one thing in one place and something else in another.
  - `block=False` for the skip path: a spin-wait loop must not busy-spin off a
    TTY, but a skip loop already does real work per phase and must not pay 0.2 s
    × N phases to discover there are no keys.
  - A user-quit during skips is now filed as `interrupted`, not `skipped`.
    `skipped` asserts the corpus already had those measurements, which is a
    different statement from "the operator stopped it".
  - **CLI option audit (one pass, all 29 `--` options): no dead options.** The
    only candidate, `--release-unreproducible`, is a false positive from a
    `getattr(args, ...)` read and is genuinely wired — it sets
    `plan.rerun_unreproducible`, consumed as `release_drop`. Both `--release-*`
    flags reach the plan correctly. What was missing was a check that this stays
    true, so `tests/test_interactive_keys.py` now fails if any option is declared
    and never consulted, and if any option is absent from `--help`.
  - README §1's stated contract said the keys were active "during active
    benchmarking and thermal cooldown sleep" — the incomplete contract that let
    this ship. It now names the skip path explicitly.
  Covered by `tests/test_interactive_keys.py` (12 tests). The regression is
  load-bearing: reverting the skip branch to a bare `continue` fails 3 of them.

- **2026-10-05** — **`verify_run.py`: the append-only law finally has a checker.**
  Verifying the trial needed shell one-liners in `/tmp`, which is the same
  scratch-the-answer-away pattern `run_status.py` was built to end. The law
  (`knowledge_base.md` §10) makes overwriting benchmark data project-blocking,
  and nothing could *check* it: `registry.config_fingerprint` and
  `scheduler.generate_fingerprint` hash kernel CONFIGS, and consolidate's
  `PRAGMA integrity_check` only proves the SQLite file is intact — none of them
  notice a phase's CSVs being rewritten. Three subcommands, CPU-only, no gate
  arithmetic reimplemented (the clock funnel reads through `TensileDriver`'s own
  loaders, so it cannot disagree with the pipeline that made the verdict):
  - `snapshot` / `diff` — per-run-directory file counts and bytes plus registry
    row counts. A new run dir and more rows is additive; anything shrunk,
    removed, rewritten in place, or any lost row exits non-zero. Snapshotting
    twice over the current corpus is clean (13 run dirs, 41 runs / 612 phases /
    49,540 records). A missing table reports as unknown, never as zero.
  - `telemetry <run_id>` — the per-phase funnel (rows → busy → sclk range →
    thermal), so a filter that discards everything is visible instead of reading
    as "the run measured nothing". That is precisely the shape of the busy-gate
    defect above, which was invisible until counted by hand.
  - `cheapest --family ZZ` — cheapest *legal* live-deck phase, with the exact
    `--targets` command to drive it. Legality comes from `consolidate._is_legal`
    because sorting by volume alone returns configs Tensile rejects at assembly.
    It reads the LIVE `phases.yaml`, not `load_deck()`'s 1644-phase universe, so
    the suggested target is always one the driver can resolve — verified by
    dry-running the tool's own suggestion back through `port_tensile`.
  Covered by `tests/test_verify_run.py` (18 tests); the failure paths get as much
  attention as the happy one, since a checker that cannot fail is worse than none.

- **2026-10-05** — **First native run on the locked deck: `run_20261005_170141`.
  It validated phase-resolved telemetry, confirmed the ZZ fix end to end, and
  exposed that the telemetry clock gate was throwing the data away.** One phase,
  `phase_zz_Ailk_Bjlk_mt32x32x16_tt2x2_vw1_wgm4_alu` — deliberately the cheapest
  legal cell in the deck (128³ primary, ZZ, `vw1`), because it is the config the
  ZZ=16 fix exists to make legal.
  - *The fix holds under real compilation.* The phase assembled and produced all
    5 shapes × 8 seeds (128³…1024³, medians 4.5 / 20.6 / 20.3 / 19.0 / 22.4
    GFLOPS). Under the old `ZZ = 8` table this phase's `VectorWidth=1` was not
    the thing that broke, but its siblings at `vw2` were rejected at assembly with
    `GlobalLoadVectorWidthA * DataType.numBytes() > 16`; nothing dead now ships.
  - *Phase-resolved telemetry works.* 1,916 of 1,950 rows carry `phase_id` (the
    34 without it are pre-phase startup), giving a real per-phase clock base of
    **1787 MHz @ 76 °C median, 82 °C max** — the first phase-owned clock in the
    project. `WinnerFreq`/`Power`/`Temperature` were 0 in all 40 benchmark rows,
    reconfirming that `logs/telemetry.csv` is the only clock source.
  - *`gpu_busy_percent` is not a usable gate, and had been silently deleting the
    evidence.* Clock bases are built from `busy > 50%` samples; that filter kept
    **1 of 1,916**. amdgpu reports 3–8% for short and small kernels, so the gate
    measured saturation, not activity. `power_uw` is no substitute (idle median
    20 W vs clocked 23 W, idle p95 28 W, quantised). The gate is now **off by
    default** (`TELEMETRY_REQUIRE_BUSY = False`) and retained for reporting only:
    `sclk` is the discriminator that works, and `SCLK_MIN_HZ` already removes the
    400 MHz idle floor. Corpus impact measured, not assumed: 53,860 → 93,427
    usable samples, phase coverage 3375/3654 (92.4%) → 4167/4516 (92.3%), i.e.
    bases get ~1.7× more samples and cheap phases become measurable, while the
    coverage *rate* — and so every existing clock-adjusted verdict — is unchanged.
  - *Nothing pre-existing was touched.* Every run directory fingerprint is
    byte-identical before and after except the new one; the registry went 40 → 41
    runs and 49,538 → 49,540 records with the old rows intact.
  - *What a cheap run still cannot do:* settle form-vs-thermal. That needs the
    same kernel in both invocation forms on the same cell, which is the exact
    comparison the certainty tiers refuse to grade. Plumbed, not answered.

- **2026-10-05** — **The "~2× invocation-form swing" is real, and grading no longer
  depends on it.** The long-standing caveat — identical config at 658.2 GFLOPS
  multi-shape vs 333.0 GFLOPS single-shape at `1000³`, larger than every graded
  effect — survived an attempt to retract it, which is itself the useful part:
  a live-tree-only search missed `archive/gfx90c_runs/run_20261002_021805` and
  `logs/telemetry.csv`, and both halves of the claim are genuine measurements.
  Verified from raw per-seed rows: the single-shape phase median is 313.0 (max
  seed 333.0), the multi-shape phase median 624.5 (max seed 658.2), **2.00×**,
  with 2 of 3 derived Tensile solution sets byte-identical between them and
  identical `LDA/LDB/LDC/LDD` and `TotalFlops=2e9`. Clock is ruled out: busy-only
  core-clock medians are 1587 MHz vs 1650 MHz (4–8%) against a 2× gap.
  The same gap reproduces inside one run (`Cijk_Ailk_Bjlk_SB_MT96x96x16_SN_K1` at
  `1000³`: 394.3 vs 855.1 = 2.38×) with identical parameters, but it cannot be
  attributed to form, because form is confounded with generator (single-shape is
  94% Tensile AutoTuner, multi-shape is entirely deck sweeps) *and* with the
  run's time window (`phase_ss_*` 00:00–06:44 vs `phase_auto_*` 06:58–09:28), and
  it inverts sign across sizes (0.25× at 256³, 1.00× at 4096³). Three changes
  follow:
  - *Certainty no longer rests on shape count alone.* `ab_audit.py` gained
    `phase_family()` (`auto` vs `deck` — keyed on the generator, not the raw
    prefix, since the live deck's `phase_<cell>_*` and the floor's `phase_ss_*`
    are the same sweep generator) and grades `certain` only on same form **and**
    same generator **and** a margin beyond noise. Otherwise:
    `form_mismatch`, `generator_mismatch`, `within_noise`, `missing`.
  - *The ±5% tie band was unsupportable and is no longer used.* Repeat spread of
    one identical kernel under one identical form (n=1495 groups): median CV 8.1%,
    p90 27.8%, worst single-shape 36.1%, worst multi-shape 75.0%. Grading now uses
    `max(cross-arm band, repeat p90) = ±27.8%`, computed from data every run.
  - *The six "certain losses" were an artifact of the old band.* At −14.5% to
    −16.1% they sat entirely inside the repeat tail; the audit now reads
    **8 WIN / 30 TIE / 0 LOSS**, and every surviving win is far outside the band.
  Instrumentation gap recorded for the next native run: all 8113 Tensile CSVs have
  `WinnerFreq`/`WinnerPower`/`WinnerTemperature` = 0 in every cell, so clocks live
  only in per-run `logs/telemetry.csv`, whose historical files predate the `phase`
  column. `telemetry.py` now samples at 10 Hz with per-phase attribution, making
  the form-vs-thermal question answerable by measurement for the first time.

- **2026-10-05** — **Measurement paths made non-destructive, and the ZZ width
  bug was found a second time in a second place.** A sweep for write paths that
  could destroy prior measurements turned up four, plus a duplicate of the same
  wrong constant:
  - *`scheduler.FAMILY_BYTES_PER_ELEMENT["ZZ"] = 8` had been fixed, but the same
    number was hardcoded a second time in `all_runs.py` (`DTYPE_BYTES["Z"] = 8`)* —
    the "one fact, one canonical home" rule violated by the byte table itself. It
    now reads widths through `consolidate.dtype_bytes()`, and
    `tests/test_measurement_integrity.py` asserts the two tables agree for every
    family, so a future drift fails a test instead of quietly understating a
    width. `all_runs.py` had also mapped `HS`/`HS_HPA` to `H` (2 B) while
    `scheduler` mapped them to `S` (4 B); both now use the widest loaded operand,
    matching `scheduler.cap_vector_width`.
  - *Re-running a run directory silently reused it.* `create_run_dir()` now
    refuses a populated `run_id` unless `allow_existing=True`, and the DB
    checkpoint upserts on conflict instead of colliding on `UNIQUE(run_id)` —
    deliberate continuation works, accidental reuse cannot start.
  - *`consolidate.install()` overwrote the live floor lock.* It now moves the old
    lock into `archive/gfx90c_runs/superseded_locks/` with a timestamped suffix
    before writing the new one; there is no `rmtree` left on that path.
  - *A phase rerun would overwrite `2_BenchmarkData/*.csv`.*
    `TensileDriver._run_tensile_benchmark()` now raises `FileExistsError` before
    launching if a phase already has results.
  - *`telemetry.py` would append 9-column rows to a legacy 8-column file,* making
    the CSV unreadable to older readers. It now compares the header and starts a
    `telemetry.<n>.csv` sidecar on mismatch.
  Regression coverage for all of the above lives in
  `tests/test_measurement_integrity.py` (17 tests); the full suite is 211 tests.

- **2026-10-03** — **Corpus consolidated; the gfx900 floor is locked, the deck is
  reduced to 29 phases, and the legality gate no longer ships dead ZZ configs.**
  Four defects surfaced while building the lock, each of which had been silently
  shaping results:
  - *The global-load byte cap was not enforced anywhere CPU-side.*
    `occupancy_feasible()` and `assembly_class_valid()` both pass a
    complex-double phase at `VectorWidth=2`, and Tensile rejects it at assembly
    with `GlobalLoadVectorWidthA * DataType.numBytes() > 16` — 16 bytes for `Z`,
    because complex double is 16 B, not 8. The cause was
    `scheduler.FAMILY_BYTES_PER_ELEMENT["ZZ"] = 8`, one number wrong, and
    `check_candidates.py` inherited it. 28 archived phases are affected and one
    whole overnight run was spent proving it. `consolidate._is_legal()` now runs
    all three gates and reads byte widths from `Tensile.DataType.properties`
    (`numBytes() == reg * 4`) rather than from a hand-maintained table.
  - *Selecting the floor by best-single-CSV-per-phase understated it.* Choosing
    one source run per phase gave a floor below the chain best on 17 of 38 cells,
    by up to 11.9%. A lower floor flatters the native arm, so the bias pointed
    the wrong way. The lock now pools **every** CSV from the chain (3802 files,
    2194 phases) and lets the canonical aggregator take the median.
  - *The pipeline was not idempotent.* The locked floor was named from a
    timestamp, so every re-run minted a new `gfx900_ref_locked_*` id and left the
    previous one behind looking authoritative; and the DB insert appended a
    duplicate row. The id is now `sha256(chain)[:10]` and the insert is scoped
    `DELETE`-then-reinsert for that one `run_id`. Re-running `all --commit`
    twice leaves row counts identical.
  - *Selection read the live deck as its candidate pool.* After a consolidation
    the deck *is* the output, so the next pass had only the survivors to choose
    from and collapsed 45 → 17. `load_deck()` now unions every `archive/phases.yaml.*`
    with the live deck, so the universe is all 1644 solutions ever written and
    re-running reproduces the same 29.
  Locked floor: `gfx900_ref_locked_52149f315d`, from the 3-run chain
  `20260929_164544_resume → 20260926_201843_resume → 20260925_152942`.
  Deck: 29 phases covering 38/38 target cells, every entry a verbatim copy of an
  archived phase, every cell's best *measured* solution retained, including the
  six current losses. `run_20261002_021805` (1168 single-shape phases, 0
  multi-shape) moved to `archive/gfx90c_runs/` — out of the live loader path but
  preserved, since its configs are deck priors. Nothing was deleted; 25
  empty/no-record phantom run dirs were moved aside and their registry rows left
  in place.
- **2026-10-02** — `family_timing` was computed on every report and then
  **never written** — the whole per-family cost block was dropped on the floor.
  The report now carries an `execution_timing` block (native run wall clock,
  reference-chain wall clock, phase-busy time) and `family_timing`, in the JSON,
  the HTML, and the one-line summary. Native run and chain are separate numbers
  on purpose: the floor is a 3-run chain, so one combined "runtime" would
  understate it. Measured on the current corpus: native `1d 19h 39m`, chain
  `3d 20h 34m`.
- **2026-10-02** — `run_status.py` wired into the TTY via `LiveStatus`, on by
  default (`--live off` to disable, `--live-interval` to tune). A background
  thread repaints a compact panel so it keeps advancing while a phase blocks,
  and stdout is wrapped so the run's own prints clear the panel first. Degrades
  to plain appended lines when stdout is not a terminal, so piped logs stay
  readable. `build_report` raises `SystemExit` when the registry is absent —
  not an `Exception` — so the first run of a fresh tree would have died in the
  panel's first frame; the panel now catches `BaseException`.

## [Acceptance best-vs-best default + telemetry-adjusted bases] 2026-09-27

- **All-zero acceptance report FIXED (arm-scope asymmetry).** The spoof arm resolved
  across the whole gfx900 reference chain (1,881 completed cells) while the native arm
  read only the reported run. `run_20260926_201835` executed 8 non-duplicate phases
  (402 were `identical_fp_already_passed`) and all 8 died on
  `Generating kernel source resulted in error 4` = `overflowedResources == 4` =
  **Occupancy limit** in the ZZ/double assembly writer → 0 native cells → every family
  `measured_cells=0`, `per_cell_verdicts=[]`, all 38 deck cells RED/MISSING at 0.0.
  The zeros were deterministic, not random.
- **Native arm is now whole-db.** `port_tensile._native_records_all_runs()` aggregates
  every `gfx90c_runs/run_*` dir's CSVs plus every registry `benchmark_result` row
  (deduped on phase/fingerprint/GFLOPS), each stamped with `source_run`;
  `_native_analytics_all_runs()` does the same for coverage/RED/ORANGE. Winners —
  including prior older winner runs — are picked across all history, matching how the
  spoof arm already worked. `gfx900_ref_*` is never admitted as native.
- **Delta-semantics bug FIXED (columns did not reconcile with the percentage).**
  `delta_pct` was computed from the cell's **max raw sample** on both arms while the
  report's "Best native median" / "Spoof median" columns displayed **medians**, so the
  displayed ratio never matched the printed delta (CC 192: displayed 31.4 vs 31.5 =
  −0.3%, reported −6.1% from underlying 40.49 vs 43.12). All statistics are now
  **per-kernel-median-first** so one lucky seed cannot decide a verdict, and the
  default `best_median` is exactly `native_best_median / spoof_median - 1` — the deck
  winner's per-kernel median vs the floor's median of per-kernel medians, term for
  term with the two displayed columns.
- **Kernel medians are keyed by source run.** The same `(phase_id, fingerprint)`
  benchmarked by two runs was pooled into a single "kernel median", averaging across
  runs; it is now one median per (run, phase, fingerprint).
- **Rendered columns can no longer disagree with the delta (second delta bug).** The
  two A/B columns were hard-wired to "Best native median" / "Spoof median" regardless of
  the basis in use, so switching basis silently re-broke the guarantee fixed above. They
  now render `native_value` / `spoof_value` — the operands actually divided — under
  basis-aware headers (`report._BASIS_HEADERS`). Verified 0 mismatches in JSON and in all
  38 HTML rows (residual ≤0.44pp = 1-decimal display rounding).
- **Default comparison basis is now `winner` = BEST vs BEST** (both arms' best
  per-kernel median), the drop-in-replacement question: replacing shipped kernel X with
  native X' compares the two arms' best candidates. `winner_clock` / `median_clock` add
  telemetry adjustment; `floor_best`, `strict`, `best_median`, `median`, `throttle`,
  `best` remain selectable. All statistics are per-kernel-median-first, so "best" means
  the best *kernel* over its seeds, never the single luckiest seed.
- **Telemetry-adjusted bases implemented and independently verified.** Each kernel's
  median is scaled by `sclk_ref / sclk_measured` from its own phase's sustained clock,
  with ONE shared corpus-wide `sclk_ref` (1800 MHz) so neither arm is rescaled in its
  own favour. Per-phase clock comes from `logs/telemetry.csv` (busy-filtered median,
  >= 3 samples, idle floor excluded). Verified against an independent recompute from the
  raw benchmark CSVs + telemetry: 38/38 cells match on both the raw best and its
  normalized twin.
- **Two guards stop the clock adjustment from producing confident nonsense.**
  (1) A phase whose only busy samples sit at the 400 MHz idle clock is dropped, not
  scaled — scaling it 4.5x let a 20.7 GFLOPS kernel "win" a cell at 93.0 GFLOPS;
  genuinely throttled phases (0.9-1.2 GHz) are kept. (2) `CLOCK_MIN_COVERAGE = 0.5`
  gate, applied SYMMETRICALLY: a clock-adjusted best is only comparable if drawn from
  the same population as the unadjusted best, and at 9% coverage (CC cells) the eligible
  subset's max sat 52-67% low, flipping CC to native wins. Below the gate both arms fall
  back together to the unadjusted twin (`winner_clock` -> `winner`) and report
  `clock_adjusted: false`.
- **The native arm has no clock data, so `*_clock` is honestly inert today.**
  `run_20260919_213727` (4,896 of 6,790 native records) has no telemetry file;
  `run_20260920_235815` has 458 all-idle rows and predates `phase_id` tagging. Native
  clock coverage is 0.000 on all 38 cells, so every `*_clock` run degrades to its
  unadjusted twin with a printed warning. The spoof arm is well covered (mean 0.74,
  1,719 tagged phases), so the machinery is real but cannot be applied symmetrically
  until native is re-benchmarked with the phase-tagging sampler. Adjusting only the
  spoof arm would deflate the floor and flatter the deck.
- **Winner provenance in the report.** `analytics.compute_native_vs_spoof_delta` now
  reports `native_winner_run`/`native_winner_phase`/`native_runs`/`n_native_runs` per
  cell; `ABVerdict` + the JSON/HTML carry them, and the HTML provenance line states the
  native arm scope. An empty native arm now prints a loud warning and the summary says
  so, instead of rendering a clean-looking all-zero grid.
- **Measured result on the new default (best vs best): 14 WIN / 10 TIE / 14 LOSS.**
  Native arm = 6,790 cells from 2 runs (`run_20260919_213727`, `run_20260920_235815`);
  coverage **100% of deck cells in all 7 families** (was 0%), **0 RED / 13 ORANGE /
  25 GREEN**. Losses are modest and cluster at large shapes (HH:4096 −14.5%,
  HH:2048 −14.6%, SS:2048 −15.1%); wins are large (HH:256 +272%, SS:256 +227%,
  HH_HPA:512 +188%) but are partly a pool-size artifact, since the floor's best is a max
  over ~303 kernels/cell vs the deck's ~75. On stricter bases the deck fares worse:
  `floor_best` 3/7/28, `strict` (per-cell dominance) **0/0/38**, `median` 23/7/8.
  `overall_pass=False`.
  **Caveat:** the basis is pool-size biased against the deck — the floor averages 303
  candidate kernels per cell vs the deck's 75 (larger in 35/38 cells), so a `max` over
  the floor is biased upward. Part of the 28 losses is that asymmetry, not kernel
  quality. The decisive artifact remains a per-fingerprint pairing (native X' vs shipped
  X), which per-cell rollups cannot express. Per-cell numbers in `results.md` §10.
- **Reference floor chain complete.** `gfx900_ref_20260926_201843_resume`: 1,212
  targeted, 808 completed, 404 failed → chain **1,881 completed / 404 unique failed =
  2,285 decided, 0 undecided**. 116 base failures retried and failed again; 288 new.
- **Open (not fixed here).** `_write_phase_config` still returns early on the
  assembly-class gate without writing the config, so `execute_phase` launches Tensile
  against a missing path — the 121 rc=1 bucket. Reference-deck generation should
  pre-filter those configs. Tracked in `implementation_plan.md`.

## [Named workload cells + reference-floor A/B fix + HPA case-sensitivity] 2026-09-26

- **A/B floor binding bug FIXED (`ccd7fed`).** `port_tensile.py` `_compute_ab_verdicts`
  bound the spoof floor from the wrong tuple slot (`ref_records, _ = _ab_records_from_csv(
  ref_dir, force_arm="spoof")` puts all records in the second element), silently dropping
  the floor → "0 WIN / 0 TIE / 0 LOSS" reports. Corrected; the same run now yields
  **30 per-cell verdicts (18 WIN / 9 TIE / 3 LOSS)**.
- **Workload-cell naming (fix.md applied, `ccd7fed`).** Every measured row is stamped
  `arm` + `cell_key` (`"<FAMILY>:<SHAPE>"`) + `kernel_key` via `gfx90c_common`
  `cell_key()`/`kernel_key()`/`shape_side()`; `analytics.compute_native_vs_spoof_delta`
  now pairs by workload cell `(family, dtype, shape)` on BOTH arms (best-of-cell median,
  ±5% tie) instead of spoof-per-fingerprint vs native-per-cell.
- **Live DB stamped (`ccd7fed`).** `gfx90c_results/registry.db` backfilled — 3,369
  measured rows carry `cell_key`/`arm`/`kernel_key`; pre-backfill backup at
  `backups/2026-09-26_impl/registry.db`. Added `idx_cell_key` index — NOTE:
  `registry.py` does not create it, so a fresh DB lacks the index.
- **HPA case-sensitivity FIXED (`58245c8`).** `_write_phase_config` matched
  `"HPA"/"HS_HPA"` case-sensitively, so lowercase agent mutants (`mutate_hh_hpa_…`,
  `mutate_hs_hpa_…`) ran as plain FP16 without `HighPrecisionAccumulate`/
  `DestDataType`. Now uppercases + consults `FamilyLabel` (consistent with
  `assembly_class_valid`); `agent.mutate_and_feed` stamps `FamilyLabel` on mutants.
  Verified against all 6 label shapes (deck / reference / mutant). Closes the
  round-2 HS_HPA pending item: HS_HPA 16 cells run at MT64x64x16 with the
  `GLVW==VW-or-1` mirror predicate.
- **Analytics cleanup (`58245c8`).** `analytics.py` dropped unused
  `cell_key`/`kernel_key` imports.
- **Corrections to earlier entries (append-only).** The "Shim removed:" bullet's
  "deleted" claim is technically inaccurate — `tensile_gfx90c_port/` source is gone
  from git, but shim-era `__pycache__` `.pyc` residue remains on disk (untracked;
  scheduled for cleanup). The bottom "Upstream baseline" section's "pristine HEAD,
  shim-only" wording is fully superseded by the native 2-file `Common.py` +
  `AsmCaps.py` patch entry.

## [Graceful gfx900-reference resume + completeness gate] 2026-09-26

- **Reference runs are now resumable.** `tensile_library.reference_chain()`
  returns the newest completed, non-smoke `gfx900_ref_*` run plus its
  `resume_of` ancestors as one logical floor; `port_tensile` `--gfx900-reference
  --resume` creates `gfx900_ref_<ts>_resume` targeting ONLY the base deck's
  phases with no completed verdict (unattempted + failed-again once), reusing
  the completed base phases as-is (`_chain_phase_sets()` distinguishes
  completed vs decided). A/B verdicts (`_compute_ab_verdicts`) and family
  timings now recall the WHOLE chain, not the newest run alone, so cells split
  across base and resume are never lost.
- **`--auto` completeness gate.** If a completed reference run exists but the
  deck has undecided phases, `run_auto` now resumes it first and refuses to
  proceed with ANY tuning until `_reference_remaining() == 0` (every shipped
  phase has a verdict — completed, or enumerated-invalid `failed`). Previously
  a truncated (47%) run was silently recalled as the floor and the remaining
  ~1096 phases were permanently dropped. `--gfx900-reference --resume` alone
  returns `noop` when the deck is already complete.

## [Run-wide telemetry + gpu_busy_percent path + peak-table reconciliation] 2026-09-25

- **Telemetry is now run-wide, not per-phase.** `telemetry.py` `TelemetrySampler`
  gained `set_phase()` + a `phase_id` column and a restart-safe `start()` (header
  written only when missing; never truncates). `port_tensile.TensileDriver` keeps
  one sampler per run dir via `_ensure_telemetry()`, tagging every row with the
  active phase in `execute_phase` and clearing the tag in its `finally`. Previously
  each phase created a fresh sampler whose `start()` truncated `telemetry.csv`, so
  a ~9.5h run kept only the last (~46s, itself an idle failed-at-compile ZZ phase)
  window — the root cause of "telemetry only measured for ~40 seconds".
  `run_gfx900_reference` stops the sampler on its run-dir swap. `report.py` reads
  the CSV by column name (`csv.DictReader`), so the extra column is transparent.
- **gpu_busy_percent path hardened.** Primary discovery now requires the candidate
  card dir to actually expose `gpu_busy_percent` (rejects connector dirs like
  `card1-DP-1/device`, which symlink to the card node and have no busy file); the
  `/sys/class/hwmon` fallback no longer appends `/device` (double-suffix never
  resolved → busy would always read 0 if the fallback ever fired), and a sampler
  that cannot find the busy file prints a one-time warning instead of silently
  logging zeros. The surviving run's busy=0 was *correct* data — its last phase
  failed during compilation (GPU never woke; sclk pinned 400 MHz).
- **Peak/ceiling tables reconciled** (`gfx90c_common.py` is the single authority;
  `gfx90c_theoretical_limits.md` §5 now quotes its exact values). Added the missing
  BF16 `1109` and INT8 `881` entries to `REALISTIC_CEILINGS`; §5 updates 1119→1118.7
  (SS/CC/HH_HPA/HS_HPA), ~98→98.6 (ZZ); §2.1 notes `PEAK_GFLOPS['FP64']` stores the
  rounded 101 (vs derived 100.8). Removed the stale "(replaced by …)" comment in
  `gfx90c_common.py`.

## [Shipped-dat gfx900 reference floor + red/orange cell semantics] 2026-09-25

- **New `tensile_library.py`.** Parses the system ROCm `TensileLibrary_*_gfx900.dat`
  binaries directly (msgpack length-prefixed solution names, marker-canonicalized
  `Cijk_...`), unions every installed ROCm prefix (`/usr` + `/opt/rocm`), emits one
  spoof phase per shipped kernel with its MT/WG/VW/DepthU/GSU knobs, and pins the
  result once at `gfx90c_results/gfx900_shipped_manifest.json` (pin-on-first-load,
  `refresh=True` re-scans). Live expected counts: SS 959, DD 96, HH 223, CC 64,
  ZZ 26, HH_HPA 424, HS_HPA 493 → **2,285** distinct shipped kernels (the old 3,066
  was per-file token counting). Config generation validated on all families
  (2,164/2,285 assembly-legal under the class gate).
- **One-time reference run (`--gfx900-reference`).** Benchmarks every shipped
  gfx900 kernel once (ScheduleName `vega10`, `FAMILY_SHAPES` deck) into a dedicated
  `gfx900_ref_*` run; later A/B `_compute_ab_verdicts` *recalls* it forever instead
  of re-running per-run baselines. The 8 hand-authored `*_baseline_*` phases were
  removed from `phases.yaml`; `run_auto` now just checks the reference run exists.
- **RED = MISSING, ORANGE = <50%.** `analytics.classify_cell_status` classifies each
  gfx900 contract cell `(family, deck-shape)` from `FAMILY_SHAPES` (38 cells):
  RED if unmeasured this run, ORANGE if best measured candidate is below the
  family realistic ceiling threshold, else GREEN. `report.py` gate/summary/JSON/HTML
  reworked to these semantics, with per-family coverage denominators now derived
  from the pinned manifest and the reference-run provenance embedded in the report.
- **Perf fix.** `_ab_records_from_csv` re-parsed the 9k-line `phases.yaml` per CSV
  (hundreds of parses per report); it now builds a phase-id → phase dict once
  (~120s → ~1s per report regeneration).

## [Cruft audit + convergence contract + CLI stage dispatch] 2026-09-25

- **Convergence contract fixed (`agent.converged()`).** Removed the `iteration < 10`
  bypass; budget exhaustion is now a STOP that returns `converged=False` (never
  reported as a pass), and a CV ≤ 15% per-cell stability gate was added via the new
  `CellAnalytics.cv` field. Criteria: no below-ceiling cells, ≥3 configs/cell, ≥2
  independent runs/cell.
- **Mutation family loss fixed (`agent.mutate_and_feed`).** Winners now harvest their
  `.family` token, mutation derives the Tensile DataType from `FAMILY_DTYPE_CHAR`
  instead of raw dtype char, so HH / HH_HPA / HS_HPA winners no longer silently fall
  back to FP32. Harvest/emit now carry `is_below_ceiling`; agent construction dropped
  the unused `max_iterations`/`red_threshold_pct` kwargs (driver updated).
- **Single-path retirement.** Removed dead `classify_retirement_tier`,
  `apply_d2_4_protection`, `classify_tie`, `should_repeat`, `classify_stability`
  (policy.py) and registry `append_records`/`get_run_info`/`get_latest_run_dir`/
  `has_phase_passed`; retirement is the single Tier-2 path via
  `check_retirement_eligibility` + `should_run`/`is_config_retired`.
- **`--stage 1-7` dispatch + bugs.** `create_run` now recognizes stage `"7"` (the old
  `"report" in args.stage` never matched the number, minting stray runs); read-only
  stages 2/4/5/7 no longer create runs; stages 1-5 have explicit handlers (preflight /
  candidate plan / benchmark / retirement sweep / analytics summary).
- **`--force` no longer a no-op.** Wired as `opt_in_identical_skip=False` through
  `run_auto` (flag was previously parsed but never read).
- **RED semantics rename.** `is_red` → `is_below_ceiling` (report RED = missing
  contract cell stays untouched); `Red` → `below_ceiling` in harvest/convergence.
- **Coverage metric fixed.** `_compute_family_coverage` denominator is now the
  contract deck (`FAMILY_SHAPES[family]`, coverage = deck cells measured); the
  shipped-kernel footprint moves to informational `footprint_pct` in the report.
- **Centralized maps.** `REALISTIC_CEILINGS` (SS 1118.7 / DD 98.6 / HH 2461.0 /
  ZZ 98.6 / CC 1118.7 / HH_HPA 1118.7 / HS_HPA 1118.7) and `FAMILY_DTYPE_CHAR` are
  now both canonical in `gfx90c_common.py`; `tensile_library.py`, `analytics.py`,
  `scheduler.py`, `report.py`, `agent.py` import them (family decks use
  `MAX_WAVES_PER_CU` instead of a hardcoded 40).
- **Dead code / imports / state removed.** Local unreferenced `TelemetrySampler`
  class + `termios`/`tty`/`Set`/`PEAK_GFLOPS` imports in `port_tensile.py`;
  `MANIFEST_KEY`/`expected_kernels_from_manifest` (tensile_library.py);
  `persist_analytics`, `THEORETICAL_PEAKS`/`DDR_ROOFLINE_GBPS` deps (analytics.py);
  `compute_ab_verdict`, `_family_to_dtype`/`mapping_path` (report.py);
  `classify_bound_class` (scheduler.py); orphan
  `tools/__pycache__/merge_draft_gfx90c.cpython-314.pyc`.
- **Regression caught & fixed during the audit.** `_KNOWN_FAMILIES` (analytics) lost
  its lowercasing when re-derived from `FAMILY_DTYPE_CHAR`, breaking every
  `extract_family_from_phase_id` match, and the `dtype_to_family` fallback collapsed
  the ambiguous `'H'` char to `HS_HPA`. Both fixed (lowercase prefix set; first-wins
  char map → `'H'` = HH). Regenerated report identical to baseline: `Acceptance FAIL:
  0 WIN / 0 TIE / 0 LOSS, 0 RED (missing) / 15 ORANGE (<50% ceiling)`.
- **Docs sweep.** Replaced stale 3,066 pip-count references with the live 2,285
  manifest split in `implementation_plan.md`, `knowledge_base.md`,
  `knowledge_base_final.md`, `incomplete_work.md`; updated RED-list/RED-cell
  terminology and dead-helper mechanism claims; expanded the `gfx90c_common.py`
  single-source-of-truth row.

## [Assembly-class gate + 295-phase deck + draft-merge tooling] 2026-09-20

- **Class-based Assembly gate (`scheduler.assembly_class_valid`).** Faithful to
  the Tensile SolutionStructs rejects reproduced from the 24 draft-run failures:
  GSU>1 on complex, GSU>1 on half+f32-accum (HPA), GSU>1 on half without
  `AssertFree0ElementMultiple>=2`, and `DepthU * BytesPerElement > StaggerUStride`
  (complex DU>=32) are all illegal on gfx90c (no MFMA). Wired at BOTH seams:
  `scheduler.validate_config` (mirror gate) and `port_tensile._write_phase_config`
  (autoskip — illegal cells never written to the Tensile deck). Class-based, so
  ANY future same-class cell is caught pre-run, not just the 24 triaged. The
  loky/semlock ValueError from the draft re-runs was benign stderr noise
  (joblib>=1.5.2 is cosmetic only); the 24 were solution-validity rejects.
- **331 → 295 phases.** Regenerated `phases.yaml` through the new gate: the 36
  GSU-2/4/8 cells on HH/HH_HPA/HS_HPA dropped (HH 56→40, HH_HPA 32→20,
  HS_HPA 28→20). 0 illegal cells, 0 fp/phase_id dups, 0 validate_config fails.
- **CASE3 merge tool (`tools/merge_draft_gfx90c.py`).** Append-only import of the
  draft run's 4962 benchmark records under the MAIN fp scheme (FamilyLabel-tagged;
  draft target_id fps were NOT portable). `.bak`-first on both registries, no
  dedup/deletion/id-reuse, retirement left to the codebase's 3-tier gate
  (policy.py:240). Dry-run reports exactly 2 retirement-eligible fps — the two
  A/B baselines (48 samples each, 2 independent runs); everything else needs a
  2nd shell from our deck. run2 added nothing new beyond the baseline 2nd shells
  + 6 auto SS@1024 cells (3 samples each, single run — reference only).
- **CASE3 import applied (run1 only).** `--runs run1` (default), run2 skipped per
  decision — its only value was the baseline 2nd shells, and the codebase gate
  can reach retirement later with 2 independent runs. Executed 2026-09-20: 445
  phase entries (baseline baselines_ss_native/spoof + 443 wide cells) + **4896
  benchmark records** appended from run_20260919_213727. Registers run1 in the
  `runs` table (completed). Backups: `backups/main_registry.db.bak` +
  `backups/draft_registry.db.bak` (draft DB untouched — read-only). Retirement
  gate re-run post-import: 0 forced retirements (no fp has ≥2 runs yet —
  baselines are single-run in main, eligible only after their 2nd shell).
  Note: first apply attempt had a phase-dedup bug that dropped the per-sample
  records after the 1st per phase (4896→445); fixed (dedup phases only, records
  always appended) and re-applied cleanly from pristine main DB. Backups use
  distinct `main_`/`draft_` tags (initial name collision would clobber main's .bak).
- **WIN/LOSS classification from merged run1** (`potential_configs.md` §6.2–§6.5).
  Empirical per-cell class vs our carried incumbents: **24 WIN cells** (draft
  best-median beats incumbent — hh 1024³ +99%, hh 2048³ +85%, hs_hpa 2048³ +70%,
  dd 512³ +68%, ss 1024³ +66%, cc 512³ +65% top margins) and **5 LOSS cells**
  (cc 256³ −23%, hh_hpa 1024³ −21%, ss 2048³ −17%, zz all RED ~23% of 98.6
  ceiling, ss 256³ parity). Next-run policy: WINs get a 2≥-shell then ≤2-knob
  mutations (per-cell table §6.2); LOSSes never re-run their fp — replaced by
  fresh structural candidates proposed in §6.3 (MT128/TT8/DUs/GSU-1, class-gated).
  Spend order §6.5: WIN shells → WIN mutations → new-wide-for-LOSS → GSU-1@4096 SS.
- **Next-increment proposal (`potential_configs.md` §6).** Wider-for-LOSS (CC/ZZ
  structural, HS_HPA admitted parms, SS GSU-1@4096), narrower-for-WIN (DD closed,
  SS/HH no double-spend), 2≥-shell-first spend order, strategy-scoped retirement.

## [Wide gfx90c candidate deck (331 phases) + --auto baseline-anchored one-command integration] 2026-09-20

- **Wide deck replaces the 304-phase manifest.** `phases.yaml` regenerated from
  `/tmp/opencode/gen_wide_deck.py`: 331 phases (SS 105, HH 56, DD 44, HH_HPA 32,
  CC 32, ZZ 32, HS_HPA 28, + 2 ss A/B baselines), every config passing the
  scheduler mirror (`validate_config` + `_validate_tensile_loads` GLVW guard) and
  per-shape M/N≥MT, K≥DepthU exact-size blockers — 0 invalid of 331.
  Structure: one phase per (family × contraction-pattern × config) bundling ALL
  family shapes, plus shape-matched underfill-GSU phases (small squares only, so
  GSU2/8 is not misapplied to large ALU squares) and DDR/GEMV phases.
- **fp-collision fix:** prior HH_HPA vs HS_HPA phases shared identical configs →
  identical sha256 fp → policy `has_fp_passed` identical-fp skip would drop the
  second family on re-runs. New deck keeps `FamilyLabel` (SS/HH_HPA/HS_HPA) in the
  fp input; all 331 phase_id/fp/config triples are unique.
- **Anchored `--auto`:** `run_auto` now runs Phase-0 preflight (non-fatal), then
  the spoof/native baseline A/B pair first as the anchor, then all manifest phases
  in order, then the convergent harvest/mutate loop — single overnight command.
- **A/B verdict pipeline fixed (was producing 0 verdicts):** completed/recovery
  records now carry `schedule_name`/`dtype`/`shapes`/`num_benchmarks` so arms
  resolve; `run_ab_test` now sources per-cell medians from `2_BenchmarkData` CSVs
  (which hold GFLOPS) grouped by arm instead of from registry records (which never
  carried GFLOPS). Verified with a fabricated 1:1 native/spoof cell set (WIN).
- **Accounting + telemetry fixes:** `phases_executed` counts only real executions
  (interrupted/skipped-by-user excluded) and reports `phases_skipped`; inline
  buggy sampler replaced by `telemetry.py`'s `/sys/class/drm/cardN/device`
  discovery (old `hwmon_dir.parent.parent` resolved to `/sys/class`).
- **Breaking CLI:** `--phases` removed (was an alias for `--targets`; the historic
  numeric `--phases 1 31 25` matched nothing). Use `--targets` explicitly.

## [HS_HPA fixes applied: manifest re-parameterized + scheduler mirror models the GLVW guard] 2026-09-19

- **Fix 1 (manifest):** the 16 `hs_hpa` phases in `phases.yaml` are re-parameterized
  from the rejected MT64x64x8/TT4x4/VW4 deck to the guard-legal MT64x64x16/TT4x4/VW4/
  DU16 parameterization (admitted `1/1 after SolutionStructs`, assembles for gfx90c).
  The accepted deck previously logged `Your parameters resulted in 0 valid solutions`
  on every pass (12 signalled, 0 valid); with Fix 1 all 16 `hs_hpa` cells are guard-legal.
- **Fix 2 (scheduler mirror):** `_validate_tensile_loads` (scheduler.py) now models the
  stock-Tensile non-MI assembly `GLVW==VW-or-1` predicate (`SolutionStructs.py:4583-4596`)
  that rejected the old deck — the mirror no longer pre-validates decks the guard rejects.
  Verified by 6 unit tests + a 304/304 phases.yaml sweep.
- Resolves the "Fix (pending)" bullet in the prior HS_HPA root-cause entry above.

## [Legacy-silence clauses enforced] 2026-09-19

- `claude.md` §8.1 written: removed machinery is **never** named in code or docs;
  history's only sanctioned homes are `changelog.md` + frozen `prior_*`; `todo.txt`
  is **USER-ONLY** (agent never reads/touches it).
- Scrub pass: `implementation_plan.md` stale references to removed launcher
  machinery reworded (entrypoint-only wording); live docs grep-clean.

## [HS_HPA rejection root-caused: Tensile GLVW==VW-or-1 generator guard; guard-legal configs found] 2026-09-19

- **Exact rejection isolated** (driver scratch `/tmp/opencode/e2e_hpa` +
  `PrintSolutionRejectionReason`): stock Tensile non-MI assembly guard
  `GlobalLoadVectorWidth{X} must be == VectorWidth or == 1`
  (`SolutionStructs.py:4583-4596`; source comment: "Restrict GRVW/VW combos so
  shift-ptr logic will work"). Fires when `setGlobalLoadVectorWidth`
  (`:2010-2047`) pv-reduces GLVW 4→2 for 64x64x8/TT4x4/VW4 tabs
  (totalElements 512 < NumThreads·GLVW = 1024, pv=2). The predicate is
  **isa-independent** (rejects gfx900 identically) — a generator/representation
  restriction, NOT a gfx90c HW/ISA limit and NOT an assembler failure.
- **Same HS_HPA intent admitted by stock Tensile on native gfx90c:**
  - MT64x64x16/TT4x4/VW4/DU16 → `1/1 after SolutionStructs`; gfx90c kernel
    assembles (`Kernels.so-000-gfx90c.hsaco`, `TensileLibrary_gfx90c.co`).
  - MT64x64x8/TT4x4/VW2/DU8 → `1/1 after SolutionStructs` and `1/1 after
    KernelWriter`.
- The 0-solution HS_HPA registry records are a parameterization collision with a
  Tensile generator guard (not a hardware incapacity); HS_HPA tuning resumes on the
  two guard-legal parameterizations.
- **Fix (pending):** scheduler `_validate_tensile_loads` lacks the `GLVW==VW-or-1`
  predicate under which the 64x64x8 deck fails — add it to the mirror.
  **Done 2026-10-14** on the harness gate (`loads.validate_tensile_loads`), with the
  `bufferLoad` / `GuaranteeNoPartialA` condition and explicit-`GLVW` reading the
  original note omitted — see the top entry.
- Docs updated: `potential_configs.md` §4 + §5.3 item 7, `implementation_plan.md`
  technical findings.

## [Native .env + toolchain resolution (industry standard) — custom chains removed] 2026-09-19

- **`.env` loading → `python-dotenv` `load_dotenv()`** (industry standard; never
  overrides live env). The hand-rolled `_load_dotenv` parser and the
  `*_CANDIDATES`/`_first_existing_*` probe chains are gone from
  `port_tensile.py`; `requirements.txt` adds `python-dotenv`.
- **ROCm discovery → native tools only:** `hipconfig` (ROCM_PATH/HIP_PATH/
  HIP_CLANG_PATH) + `shutil.which` for binaries on PATH. `.env` and README §6
  slimmed to `TENSILE_ROOT` + optional overrides; no candidate chains.
- **Guardrail added to `claude.md` §5:** never re-invent known-solved problems —
  OS/stdlib/industry-standard library wins (`.env`→python-dotenv,
  discovery→`hipconfig`+`shutil.which`, locks/DB→stdlib, CLI→`argparse`).
- **Validated:** Phase-0 preflight 4/4 and a suite-exact ActiveE2E
  (`phase_ss_Ailk_Bjlk_256x256x256_mt96x96x16_tt6x6`, rc=0, Actual Solutions 1/1,
  `TensileLibrary_gfx90c.co` + `Kernels.so-000-gfx90c.hsaco`) with the native
  resolution (scratch `/tmp/opencode/e2e_b`, isolated).

## [Docs ecosystem governance: shim & legacy-suite silence, todo.txt user-only] 2026-09-19

- **Rule codified in `claude.md` §8.1:** the import-time shim no longer exists and
  is never mentioned in code, docs, or prose; its history lives only in this
  changelog and the frozen `prior_*` files. The prior-campaign shell suite
  (`run_gfx90c_suite.sh`) is referenced only inside `prior_*`.
- **`todo.txt` is a user-only file:** the agent never reads, writes, or touches it.
- **`claude.md` native-support wording aligned** to "2-file minimal Tensile patch"
  (`Tensile/Common.py` + `Tensile/AsmCaps.py`).

## [Distro-agnostic ROCm toolchain resolution] 2026-09-19

- **`.env` fleshed out for both install styles:** ROCm paths are now probed via
  `*_CANDIDATES` ':'-chains (`ROCM_PREFIX_*`, `ROCM_BIN_*`,
  `ROCM_LLVM_BIN_*`, `TENSILE_ASSEMBLER_*`, `TENSILE_ASSEMBLER_FALLBACK_*`);
  first existing entry wins, so AMD-installer (`/opt/rocm`) and Fedora-RPM
  (`/usr/bin` + `/usr/lib64/rocm`) hosts both work from one `.env`.
- **`port_tensile.py`:** new `_first_existing_dir` / `_first_existing_file` /
  `_resolve_rocm_paths()` used by `_get_tensile_env` (PATH injection + subprocess
  `ROCM_PATH`/`HIP_PATH`) and the `--assembler` selection. Explicit env values
  still win when they point at existing paths; stale values fall back to the chain.
  Verified on live host plus synthetic AMD-only and Fedora-only scenarios
  (`/tmp/opencode/test_rocm_probe.py`).
- **README §6 rewritten** for the candidate-chain schema + fixed the residual
  "28-family coverage metrics" wording on the `report.py` row.

## [Repo relocation & report/driver hygiene] 2026-09-19

- **`file:///` references removed:** docs previously pointed at the dead
  `GPU/backrocm/porting_tensile/attempt2` path; README links now relative.
- **Hardcoded locations → `.env`:** `port_tensile.py` loads `TENSILE_ROOT`,
  `ROCM_*`, `HIP_*`, `TENSILE_ASSEMBLER(_FALLBACK)` from `.env` (shell env >
  `.env` > defaults). `.env` created in repo root.
- **Early-quit key `'e'`:** ends the run cleanly after the current phase /
  iteration (run stays `completed`, metadata `end_after_iteration: true`).
- **Verbose logs:** Tensile stdout/stderr are teed live to console (prefixed
  `[tensile]`) and to `logs/.../stdout.log`/`stderr.log`; `TENSILE_VERBOSE=1`
  appends `--verbose` (Tensile PrintLevel 3).
- **Acceptance report HTML de-hardcoded:** Problem space / coverage matrix /
  telemetry sections are now data-derived (cell analytics, registry
  started→completed timing, `logs/telemetry.csv` medians/peaks). Fabricated
  VRAM / SCLK / MCLK / GPU-busy rows dropped (sensors unavailable on this APU).
- **Report dtype fix:** `extract_dtype_from_phase_id` now uses the token family
  parser (was a regex that returned `'unknown'` for `phase_ss_spoof_baseline_vega10`);
  `'auto'` family mapped to `'S'`. The 67 red cells previously logged as
  dtype `unknown` now resolve to real dtypes.

## [Native gfx90c support replaces the import-time shim] 2026-09-19

- **Root cause of the shim:** Tensile's `populateCapabilities` runs before config
  merge, so a config-parse-time ISA injection is too late; 2026-08–09 proved the only
  shim-compatible hook was import time (`tensile_gfx90c_port/sitecustomize.py` on
  `PYTHONPATH`, 3 injections: `SupportedISA`, `architectureMap`, `getCapabilitiesCache`
  seeded from gfx90 just so gfx90c was not probed-and-rejected).
- **Replaced by real in-tree support** on Tensile latest `develop_deprecated` HEAD
  (verified equal to `origin/develop_deprecated`, `e8a8999e`): 3 minimal bookkeeping
  entries in `Tensile/Common.py` (`SupportedISA` `(9,0,12)`; `architectureMap`
  `gfx90c`/`:xnack+`/`:xnack-`) plus `Tensile/AsmCaps.py`, a first-class `(9,0,12)`
  capability entry written from scratch from LLVM `FeatureISAVersion9_0_C`
  (`HasMadMixInsts`; no MFMA / dot / dl-insts / VOP2-fmac / WMMA / kernarg-preload).
  No cloning or deriving from any other ISA.
- **Validated:** written caps == real assembler-derived gfx90c caps (0 mismatches,
  ROCm 6.4); roundtrip `gfxName((9,0,12))`/`gfxArch('gfx90c')`; `GetArchCaps((9,0,12))`
  needs no change. End-to-end with the driver's own known-good config from
  `phases.yaml` (`phase_ss_Ailk_Bjlk_256x256x256_mt64x64x16_tt4x4_3`): native
  `# Detected GPU 0: gfx90c`, "Actual Solutions: 1 / 1", kernel built, loaded
  `TensileLibrary_gfx90c.co` / `Kernels.so-000-gfx90c.hsaco`, benchmarked 434 GFlops
  @ 256³, exit 0.
- **Shim removed:** `tensile_gfx90c_port/` deleted; `port_tensile.py`
  `_get_tensile_env`/`run_preflight` stripped of shim wiring and `TENSILE_REPO_ROOT`;
  grep-clean across driver modules. Phase-0 preflight passes 4/4 shim-free.
- **Docs updated** (knowledge_base §2/§3, README preflight, mapping, claude.md tree
  + PYTHONPATH, implementation_plan) to describe native support. The "pristine HEAD,
  shim-only" wording in the `Upstream baseline` section above is **superseded** by
  this entry.

## [Phases.yaml Fixes, Telemetry v2 & Client/Bench Split PoC] 2026-09-14

- **`phases.yaml` — 48 Invalid Entries Repaired:** Reconciled NLCA and DepthU divisibility rules via in-place fixes (NLCA 3→1 ×46, DepthU 4→16 ×2); verified all 230 contraction entries pass `_validate_tensile_loads`. Archived backup at `archive/phases_20260914_prefix.yaml`.
- **`telemetry.py` — Minimal Non-Root Sysfs Telemetry:** Extracted sampler into dedicated clean module reading world-readable sysfs (`0644`), correctly resolving `mclk_hz` via `pp_dpm_mclk` parsing (resolving dead 0 mclk bug) and supporting APUs (`power1_input` fallback).
- **Client/Bench Split PoC:** Verified Tensile `--prebuilt-client` mechanism in `/tmp`, eliminating redundant per-phase CMake host client rebuilds.

---


- **`port_tensile.py` — Completion Record Recovery:** Added `end_record_logged` flag + finally-block recovery logging. If Tensile phase completes successfully but normal logging path is interrupted (e.g., Ctrl+C during final processing), the finally block ensures completion record is persisted to registry.
- **Root Cause:** Run 213103 completed phase (PASS in stdout.log, CSVs generated) but only "started" record existed in DB — no "completed" record. Normal logging path may have been interrupted before `append_record()` call.
- **Fix Mechanism:** Flag tracks successful `append_record()` call; finally block checks if result exists but flag is False, then logs completion record with appropriate status.

---

## [Immediate Keypress Listeners + MacroTile Format Fix] 2026-09-13

- **`port_tensile.py` — Raw Mode Keypress Listeners:** Added `tty.setraw()` to both cooldown and phase execution key listeners for immediate 's'/'q' detection without requiring Enter press. Terminal settings restored in finally blocks.
- **`port_tensile.py` — MacroTile Format Fix:** Corrected Tensile MacroTile schema from invalid `[[M0, M1, DepthU]]` to valid `[[M0, M1]]` format. DepthU now emitted as separate ForkParameter. Fixes "Invalid parameter value: MacroTile = [64, 64, 8]" error causing CC/DD phase failures.
- **Root Cause:** Tensile expects 2D array for MacroTile dimensions only; DepthU is a separate parameter, not third array element.

---

## [Report Generation Coverage Fix for Failed Phases] 2026-09-13

- **`report.py` — Family Coverage Detection:** Enhanced `_compute_family_coverage()` dtype matching to properly detect family-specific cells (CC/DD/ZZ) when phases fail during execution, ensuring accurate coverage statistics even when benchmark CSVs are missing due to configuration errors.
- **Root Cause:** Previous implementation only matched dtype (FP64/FP32) but not family names (CC/DD), causing coverage reports to show 0 cells for CC/DD families despite phase execution attempts.
- **Impact:** Reports now correctly reflect attempted phase execution even when Tensile configuration errors prevent CSV generation.

---

## [Multi-Threaded Compilation, MacroTile Schema Fix, Cooldown Key Controls & Immediate Reporting] 2026-09-13

- **`port_tensile.py` — Multi-Threaded Clang Compilation:** Set `CpuThreads` dynamically based on available CPU cores (`min(os.cpu_count(), 16)` instead of forced single-thread `1`), accelerating clang assembly build times.
- **`port_tensile.py` — MacroTile Tensile Schema Fix:** Corrected `ForkParameters` emission from invalid `MacroTile0`/`MacroTile1` keys to valid Tensile top-level list `MacroTile: [[M0, M1, DepthU]]` (resolving the `Invalid parameter name: MacroTile0` error in CC/DD runs).
- **`port_tensile.py` — MacroTile0/MacroTile1 Removal:** Added explicit removal of deprecated `MacroTile0`/`MacroTile1` keys from `fork_params` before YAML emission, ensuring Tensile only receives valid `MacroTile: [[M0, M1, DepthU]]` format.
- **`port_tensile.py` — Real-Time Cooldown Key Listeners:** Updated `_apply_cooldown()` to listen for `'s'` (skip cooldown immediately) and `'q'` (gracefully quit run) during thermal sleep.
- **`port_tensile.py` — Immediate Report Generation on Quit:** Ensured `acceptance_report.json` and `acceptance_report.html` are automatically generated and written to `gfx90c_results/` even on early termination via `'q'` or interruption.
- **`README.md` — Usage Documentation:** Added complete documentation for keyboard controls (`s`, `q`), semantic CLI filters (`--family`, `--pattern`, `--shape`), and HTML visual dashboard inspection.

---

## [HTML Dashboard Generator Porting & Integration] 2026-09-13

- **`report.py` — Automated HTML Dashboard:** Ported and unified the attempt1 analytics dashboard generator (`make_report.py`) directly into `AcceptanceReporter.write_html_report()`.
- **Key Features:** Emits dependency-free, responsive dark-mode HTML dashboard (`gfx90c_results/acceptance_report.html`) containing 28-family footprint progress, realistic GEMM ceiling progress bars, per-cell A/B head-to-head comparison cards, and RED-list tracker.
- **Verification:** Tested in `/tmp` POC then integrated into `report.py` and validated with live data.

---

## [Complete 7-Stage Driver Transition & Semantic Target Interface] 2026-09-13

- **`port_tensile.py` — Semantic Target Filtering:** Replaced arbitrary numeric phase arguments with first-class semantic CLI flags: `--family` (`{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}`), `--pattern` (`{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}`), `--shape`, `--stage` (`1..7`), and `--targets`.
- **`phases.yaml` — 28 Native Families Populated:** Manifest completely populated with 228 clean targets spanning all 28 mathematical contraction families with anchor problem shapes.
- **Dry-run validation:** Added `--dry-run` to query and verify target matching without triggering GPU execution.

---

## [Tensile YAML Generator Fix, Candidate Tile Validation & CSV Resilience] 2026-09-13

- **`port_tensile.py` — `_write_phase_config` fixed:** Corrected `TransposeA`/`TransposeB` derivation from contraction pattern labels (`Ailk_Bljk` $\to$ NN/FF, `Ailk_Bjlk` $\to$ NT/FT, `Alik_Bljk` $\to$ TN/TF, `Alik_Bjlk` $\to$ TT/TT); fixed `MacroTile0`/`MacroTile1` mapping from string representation; calculated `WorkGroup` dynamic tile ratios; enabled `HighPrecisionAccumulate` and mixed precision `DestDataType`/`ComputeDataType` for HPA families.
- **`scheduler.py` — candidate tile divisibility & workgroup validation:** Added validation check in `validate_config` ensuring `MacroTile` dimensions are strictly divisible by `ThreadTile` dimensions (`MacroTile0 % ThreadTile0 == 0`) and workgroup thread count is a multiple of 64 within $[64, 1024]$.
- **`analytics.py` — CSV header whitespace resilience:** Updated `load_benchmark_csv` with whitespace-stripped fieldname parsing and robust per-kernel GFlops metric extraction for space-padded Tensile CSVs.
- **Verification:** Unit tests passing 100%; benchmark CSV parser validated against 96 real kernel measurements (`run_144805`, `run_150517`, `run_151227`) showing peak 928.0 GFlops at $1365^3$.

---

## [Ctrl+C signal handler + stale-run cleanup + run status fix] 2026-09-13

- **`port_tensile.py` — Ctrl+C signal handler fixed:** `_signal_handler` now calls
  `sys.exit(130)` after killing the child process group via `os.killpg`. Previously the
  handler only set `_stop_requested=True`; the driver continued running normally after
  killing the subprocess instead of terminating. Exit code 130 = standard shell Ctrl+C.
  Run status is written to registry as `interrupted` before exit.
- **`registry.py` — `cleanup_stale_runs()` added:** bulk-UPDATE of any `status=started`
  rows to `interrupted` on driver init. Cleans up 3 orphaned runs from this session
  (run_140507, run_141220, run_143006 all set to `interrupted`). Non-destructive: only
  updates status column, does not touch records.
- **`port_tensile.py` — run status semantics:** `run_phases()` now marks run as
  `interrupted` if `_stop_requested` is True at completion, instead of always writing
  `completed`. The `run_auto()` path unchanged (it also sets `_stop_requested` on budget
  exhaustion, which is expected termination — status remains `completed`).
- **Root cause of HipClangVersion failures clarified:** `ValueError: invalid literal for
  int() with base 10: '<unknown>'` in runs 143115–144714 was a pre-symlink race: the
  `/opt/rocm/share/hip/version` symlink did not exist at run time. Symlink was created
  during the session; run_144805 succeeds with `HipClangVersion=6.4.43484`. Code not
  modified; environment is now stable.

---

## [attempt2 driver full remediation & adversarial review fixes] 2026-09-13

- **Full adversarial review remediation across the driver ecosystem:**
  - `port_tensile.py`: Fixed Stage 7 A/B test logic error (no longer passing identical datasets for native and spoof arms); added background continuous sysfs telemetry sampler (`TelemetrySampler` reading `hwmon[0-9]*`, logging canonical `Hz/µW/mC/%` with header-in-CSV); added interactive non-blocking `'s'` skip and `'q'` quit key listeners during phase execution; replaced Stage 6 stub with real YAML logic generator, `TensileCreateLibrary` runner, anti-alias scanner (0 gfx900/vega10 leaks), and 3,066 kernel regression check; eliminated subprocess pipe buffer deadlocks by logging to disk.
  - `scheduler.py`: Corrected GEMM LDS memory estimation to `(M*K + N*K) * elem_size * NLCA / 1024.0`; made `parse_tensile_shape` robust to batch (`_B16`) and explicit K (`_K4096`) shapes; improved wave-based CU occupancy estimation.
  - `agent.py`: Upgraded `converged()` to enforce the full 4-condition convergence standard (≥2 independent runs, ≥3 configs tested, ≤1% movement, and no RED cells); replaced hardcoded FP32 candidate reconstruction fallback with family-aware defaults.
  - `registry.py`: Protected `append_phase()` with `INSERT OR IGNORE` and transaction deduplication to avoid SQLite uniqueness conflicts.
- **Verification:** Unit tests and module import validations pass 100%.

---

## [attempt2 spec drift cleanup + Tensile bulk purge] 2026-09-13

**Spec drifts fixed (SD-1 through SD-7) — all imports now correct:**
- `port_tensile.py`: removed `import fcntl`; fixed docstring (flock→sqlite3 INSERT);
  `AppendOnlyRegistry` → `SQLiteRegistry`; `CandidateGenerator` now receives registry;
  `_extract_phase_number` uses regex `phase_(\d+)` (not naive split); `import re` added.
- `agent.py`: `from scheduler_fixed import` → `from scheduler import`.
- `report.py`: `from policy_fixed import` → `from policy import`.
- `scheduler.py`: `registry` param now optional (`=None`); `append_to_phases` raises
  `RuntimeError` if called without registry instead of silent crash.
- `analytics.py`: stale `fcntl.flock` docstring updated to `sqlite3 records INSERT`.
- All 7 modules import cleanly; `port_tensile.py --help` passes.

**Bulk cleanup — 35.5 GB freed from Tensile working dir:**
- `gfx90c_runs/` (34 GB), `gfx90c_results/` (1.5 GB), `build_tmp/` (75 MB) deleted.
- attempt1 SHA256-verified as complete frozen backup before deletion. Untouched.
- `/tmp/opencode/` retained by user request; purged on next reboot.

**Source of truth confirmed:** PEAK_GFLOPS values match between Tensile and attempt2 mirrors.

---

## [attempt2 persistence: SQLite approved] 2026-09-13

- **Approved change:** ledger write path is stdlib `sqlite3`
  (`gfx90c_results/registry.db`, WAL). `records` = INSERT-only `json.dumps`
  payloads. Replaces `fcntl.flock` + JSONL **as the write path**.
- **Unchanged:** append-only evidence law (`knowledge_base.md` §10); `phases.yaml`
  remains the data-only manifest; harvest still appends YAML rows; stats pipeline
  still consumes run-dir CSV (jsonl export optional until pipeline reads SQLite);
  legacy jsonl files stay on disk, never rewritten.
- **`runs` table:** operational checkpoint (status UPDATE allowed). Not evidence.
- **Retracted:** previous `[attempt2 v1 fixes implementation]` block. That entry
  claimed policy/scheduler/report/agent/driver "fixes" had landed. They had not
  (broken imports, Tensile stub, harvest inverted, RED vs 50% PEAK, YAML
  abolished in the "fixed" driver). Unapproved drifts live in
  `incomplete_work.md` §4.9 / `adversarial_review.md` §6. Do not treat
  `/tmp/opencode/*_fixed.py` as the spec.

## [attempt2 stage approval] 2026-09-13

- **All 7 driver stages approved by user:** Stage 1 (Manifest & Phase Execution), Stage 2 (Candidate Generation), Stage 3 (Benchmark Execution), Stage 4 (Adaptive Repeat / Convergence), Stage 5 (Analytics & Append-Only Registry), Stage 6 (Synthesis / Build), Stage 7 (Acceptance A/B & Final Report).
- **ASCII flowchart added to implementation_plan.md:** Visual representation of stage flow and convergence loops, including the convergence check loop (harvest → mutate ≤2 knobs → loop back to Stage 2) and --auto mode budget-controlled loop.
- **Stage specs now authoritative:** implementation_plan.md Driver Architecture section is the single source for all stage mechanics, scope, key files, and convergence logic.

## [attempt2 consolidation] 2026-09-13

- **Stage specs consolidated into implementation_plan.md:** Previous agent's Stage 4/6/7 functional specs (adaptive repeat/convergence, synthesis/build, acceptance A/B) integrated into Driver Architecture section. Stage 5 (analytics/registry) mechanics added. D2.4 decision recorded: 3 premature auto-retire records (p12 387d2577, p5 286b940a, p6 1570d91a) stay as ordinary rows awaiting ≥2-run corroboration, never marked as verdicts.
- **Core strategy and AI constraints added to implementation_plan.md:** One-shot deterministic convergence flow, AI Must Not Decide rules, Correctness Gate, Reward Hacking prevention, Manual-LLM contingency (user-invoked, add-only, ≤5 candidates). Content consolidated from separate tuning context MD.
- **README.md streamlined:** Removed duplicated hardware/target specifications (now in knowledge_base.md only). Kept orientation, philosophy, goal statement, and file locations.
- **todo.txt removed:** Task list content already in scratch.md; eliminated redundancy.
- **benchmark-retirement-sensor-logging-fixes.json retained:** 19MB session log kept for reference (user declined deletion).
- **tensile_tuning_context.md retained:** Tuning philosophy content consolidated into implementation_plan.md; original file kept for reference (user declined deletion).

## [attempt2 init] 2026-09-13

- New ecosystem folder created at `porting_tensile/attempt2/`; prior-campaign
  conclusions absorbed into `prior_INSIGHTS_CAVEMAN_ULTRA.md` /
  `prior_RESEARCH_ARCHIVE.md` (the ONLY sanctioned prior material, appended no-data-
  deletion).
- **One-shot deterministic convergence contract** authored: no LLM consultation in
  the loop; deterministic harvest → mutate ≤2 knobs → re-run until convergence.
  The ONLY exception is the user manually invoking an LLM to ADD candidate configs
  — add-only, out-of-band, never in the loop.
- **Contract sharpened (2026-09-13, user directive):** attempt2 exists to **beat the
  gfx900 spoof baseline across the entire shipped kernel suite** AND approach the
  gfx90c theoretical limit as closely as possible. The theoretical limit is fixed by
  `gfx90c_theoretical_limits.md` (rocminfo + first-party cross-checked; see that file).
- **Driver architecture folded into `implementation_plan.md`** (single self-contained
  plan): `port_tensile.py` + `phases.yaml` manifest, `json.dumps` state,
  `fcntl.flock` locking, `argparse`, single-source PEAK.
- **Every code change PoC'd in `/tmp/opencode/` until fully functional** before it
  lands anywhere near the live driver (enforced in `implementation_plan.md`).
- **No `changes_kb.md`** — absorbed here. **No `proposed_fixes.md` / `refactor_suite.md`
  / `CHANGELOG.md` / agent-log MDs** — absorbed into `implementation_plan.md` /
  `changelog.md`. Ecosystem is the lean single-owner set registered in `claude.md`.
- Peak table corrected everywhere to single-rate **1613** for BF16 and INT8 (NO
  RDNA-style 3226 assumption); single source `gfx90c_common.PEAK_GFLOPS`.
- `PHASE_TIMEOUT_S` default planned as finite (runaway protection), not unbounded.
- Interactive single-phase kill ('s' skip / 'q' quit — one phase, not the whole run)
  planned for the driver.
- Stats/HTML pipeline retained and carried forward (`all_runs_dataset.py` →
  `make_results_md.py` → `make_report.py` → `gfx90c_report.html`).

## Prior campaign 2026-09-04 .. 2026-09-13 (frozen conclusions)

- Port mechanics proven YES: 3-injection shim, Phase-0 gates 10/10, anti-alias
  0 gfx900 leak, synthesis PASS.
- Performance = **parity, not wins** on the only same-run head-to-head
  (0 win / 11 tie / 0 loss at ±5% vs the gfx900 spoof).
- Candidate suite A–G brought to **5W / 10T / 6L** over 21 shared cells
  (B GEMV 32/64×4096 +8.1/+13.6% & +17.8/+21.3%; D 2048³ +14.1/+20.1%; E int8 1024³
  +18.3%; A sgemm 2048³ stable; F = 3 new cells; C crashed every run until the
  `[{}]` fix).
- Only 6 genuinely-new problem cells produced; ~40% of prior runtime went to
  re-benchmarking known shapes.
- Best measured: FP32 1118.7 @1024³, FP16 2492.1 @4096³, BF16 1108.5 @2048³,
  INT8 881.2 @2048³, FP64 98.6 @1024³ (98% of the 101 pipe — saturated).
- Four ruler bugs found and fixed; three-tier retirement scheme in place;
  telemetry fixed to the sysfs contract; toolchain-stderr fix landed (the single most
  impactful prior change).
- Summary only here — the full conclusion detail lives in
  `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`.

---

## Prior-campaign evolution (the WHY layer)

### The port mechanism flipped

- Baseline started as a **9-file in-tree patch**; worked, but forked-the-tree drift.
  Replaced by the **3-injection Python shim**
  (`tensile_gfx90c_port/sitecustomize.py` on `PYTHONPATH`): tree stays pristine, the
  whole delta is one import-time file. The shim is the ONLY port mechanism.

### Suite evolution (driver generations)

- The driver suite iterated through several generations during the prior campaign;
  the last shell generation is frozen and inherited as the attempt2 baseline for
  migration parity (new driver paradigm — the attempt2 python driver replaces it).

### Ruler bugs (all four closed prior)

- Ruler normalization was wrong in four ways: max-anchored squares, cross-dtype
  geo-mean leaking the DDR factor, a dtype-string key no-op, and missing rulers
  fabricated as 1.0. Fixed to bound-class medians, `(dt,cls)` keyed, missing →
  **reported, never inferred**. The ruler/throttle discipline only became trustworthy
  once all four were closed.

### Retirement

- Three-tier retirement introduced. Tier-1 = identical-fp skip (default on; opts out
  via a config flag; `--phases` scoped). Tier-2 = dominance retirement by
  `auto_retire.py` (attempt2 gates on ≥2 independent runs/cell after a premature
  3-record emission). Tier-3 = peak/spoof never retires anything.

### Telemetry

- Fixed to the sysfs contract; `logs/telemetry.csv` carries its header in-file
  (self-describing; canonical Hz/µW/mC/%, `hwmon[0-9]*`, `power1_input` →
  `power1_average` fallback). Continuous whole-run sampler, 2 s cadence.

### The single most impactful fix

- **Toolchain stderr fix** — the single most impactful change of the prior campaign:
  tool stderr kept out of machine-readable outputs made the append-only result stream
  trustworthy. Every downstream pipeline depends on it.

---

## 2026-09-28 — Occupancy preflight gate; ZZ dead tiles replaced

**Why.** All 8 executed native ZZ phases (`run_20260926_201835`) ended
`Generating kernel source resulted in error 4` = `overflowedResources == 4`
= Tensile's *Occupancy limit* (register-file exhaustion, `KernelWriterAssembly.py:15422`),
not a launch failure and not the benign "error 3". They died because the
legality preflight **could not detect this class of failure at all**:
`_estimate_occupancy` inferred the thread count from `ThreadTile` via a
`64 // tt` heuristic, ignored `MacroTile` entirely, and never counted VGPRs —
so it returned ≥ 1 for every config and never fired.

**What changed.**

- `scheduler.py`: added `VGPR_PER_ELEMENT`, `VGPR_BUDGET`, `_tile_dims`,
  `_dtype_char`, `occupancy_workgroups_per_cu`, `occupancy_feasible`.
  `validate_config` and `_estimate_occupancy` both delegate to the one model, so
  there is a single source of truth. The gate **fails closed** on a dtype with no
  VGPR weight: a low guess (S=1) would re-admit a failure that a high guess (Z=8)
  catches.
- `phases.yaml`: 410 → 418. Removed the 8 dead phases (`MT 128x64x8/8x4` and
  `MT 64x128x8/4x8` × 4 contraction patterns); added 16 legal ones:
  `128x32x8/8x4` and `32x128x8/2x8` as same-aspect replacements, plus `64x64x8/4x2`
  (thread count never varied for ZZ) and `128x32x16/8x4` (deeper K). Phase IDs and
  SHA-256 fingerprints regenerated; uniqueness asserted. The pre-fix deck is kept at
  `archive/phases.yaml.pre-occupancy-gate.bak` as regression evidence.
- New `check_candidates.py`: sweeps any deck through the 4 gates
  (divisibility, assembly-class, LDS, occupancy), exits 1 on any illegal config,
  so an illegal deck can be caught before a GPU run instead of mid-run.
- New `all_runs.py`: all-runs pattern analysis over the whole DB, driving oto's own
  loaders (`_native_records_all_runs`, `_ab_records_from_csv`,
  `compute_native_vs_spoof_delta` winner semantics) so it cannot drift from the
  pipeline that produced the ledger.
- New `test_occupancy_gate.py`: 18 tests, incl. the calibration matrix, the
  ThreadTile-cancels identity, fail-closed dtype behaviour, the shipped deck being
  legal, and the pre-fix deck still failing exactly 8.

**Verification (CPU only, no Tensile launch, no GPU).** 18/18 tests pass;
`check_candidates.py` reports 0 illegal across all 418 shipped phases and exactly 8
illegal against the archived pre-fix deck.

**Honest limits.** The weights are **calibrated, not derived**: `R=8` for ZZ is the
smallest value reproducing every observed outcome, and the gate demands 2× headroom
because the raw accumulator-only count predicts `numWorkGroupsPerCU == 1` for the
tile that actually died (pinned in `test_raw_tensile_model_would_have_missed_the_failure`).
It reproduces all 9 observed cases and has zero false positives over 410 phases, but
it is a model, not a register allocator. ZZ is now **legal but unbenchmarked** — the
next step for the family is a TTY run, not more code.

---

## 2026-10-05 — Native arm flushed from registry; `run_status` default-head fix

### Native registry rows removed (user-authorised, backed up first)

The live registry was flushed of **native** rows only, so the deck would measure every
candidate instead of skipping all 29 as `identical_fp_already_passed`.

- **Backup (verified before the write):** `gfx90c_results/backups/registry.db.pre-native-flush.20261005_182448`
  — `PRAGMA integrity_check: ok`, 42 runs / 49,540 records / 612 phases, byte-identical
  row counts to origin. All 33 native runs are recoverable from it.
- **Deleted:** 35,729 records + 33 run rows (`run_*`). **Untouched:** all 9
  `gfx900_ref_*` floor runs (13,811 records), including `gfx900_ref_locked_52149f315d`
  with its 2,194 pooled phase records. `phases` (612 `draft_*` catalog rows) kept —
  it is a config catalogue, not measurements, and `should_run` never reads it.
- **Result:** `should_run` now returns approved for **29/29** deck phases under
  *default* policy; `reference_chain()` still resolves to the locked floor.
  `--force` is no longer required.

**Scope was chosen from evidence, not assumption.** Floor runs also carry `fp` and
`completed` records, so a native-only flush would not have worked had any deck
fingerprint been decided by a reference run. Checked first: **0 of 29** were
floor-decided, all 29 were native-only. There were also **0 `retire` records**, which
`is_phase_retired`/`is_config_retired` consult, so no second gate remained.

**Nothing was actually lost.** `ab_audit.py` reads `2_BenchmarkData` CSVs from disk,
not the registry, and still reports the identical 8 WIN / 30 TIE verdict against the
same 6 on-disk `run_*` directories. Only registry rows were removed.

### `run_status.py` default head: a closed interrupted run was outranking the floor

The default view headlined `gfx900_ref_20260928_155422_resume` — **interrupted, and
closed 8 days earlier** — while skipping the floor locked 5 days later. Every tier
count and ETA it printed came from the wrong corpus; a 25 h ETA derived from it was
wrong. `reference_chain()` (what `--auto` actually gates on) was never affected.

Cause: `ACTIVE_STATES = ("started", "interrupted")` treats *any* interrupted run as
active, and the selection took the newest-first match, so the scan walked past the
completed floor.

Fix — in flight is decided by `completed_at`, not the status label: prefer (1) a run
with no `completed_at` (live, resumable), then (2) the newest **completed** chain, then
(3) the newest finished-but-interrupted run.

The status label alone was the wrong axis: `test_chain_follows_resume_of` pins the
contract that an interrupted run which *never closed* stays at the head. Both
directions are now pinned by new tests, and the fix was verified load-bearing (reverting
it fails `test_closed_interrupted_run_does_not_outrank_newer_floor`).

**Verification.** `test_run_status`: 41/41. Full suite: **247 tests, OK (skipped=1)**.

---

## Session / consultation record

- **Prior campaign consumed 3 of 6 in-session LLM consultations.**
- **attempt2 consumes 0 by design.** The deterministic pipeline replaces the
  prior candidate-sweep loop entirely; a consultation would only be sanctioned to
  break a coverage deadlock — as a USER-invoked, add-only candidate injection (single
  canned prompt, ≤5 recipe mutations constrained to known-valid gfx90c knobs, dropped
  into `phases.yaml`). Never automatic; never in the loop.

## Upstream baseline

- The live Tensile repo remains at pristine HEAD, read-only, only the gfx90c shim
  applied. No upstream release entries are mirrored here.

## 2026-10-12 — Docs whittling: history archived out of the live docs

Executed the ARCHIVE half of `docs/audit.md` (§1.4, §1.5, §1.6, §1.12,
§2.1, §2.4, §4). The removed narrative is preserved verbatim below; the live
docs now state current fact only. Trimmed copies whose canonical home already
exists were marked as duplicates rather than reproduced twice:
`tensile_tuning_context.md` owns the Objective/strategy/philosophy paragraphs;
`mapping.md` owns the footprint; `oto.metrics.ab_delta` (module docstring,
`_collect`, `_stat`) owns the A/B aggregation bases and clock rules;
`oto.tensile.gates.occupancy.occupancy_feasible` owns the occupancy model;
`oto.tensile.config_writer` owns the launch-boundary gate and the 121-config rc=1
bucket. No code was changed.

Reference repairs made because kept sections pointed at moved anchors: the plan
banner's "self-contained" claim; the plan's `Hplan.10` and "status banner above
Option H" pointers; the plan's Next Move pointer to `incomplete_work.md` §4.9.

### implementation_plan.md

**implementation_plan.md — Objective (pre-trim)**
**Objective**

Produce native `gfx90c` Tensile libraries covering the shipped 28-family × 4-pattern
footprint (2,285 distinct shipped gfx900 kernels = 7 dtype/op families × 4 contraction
patterns; the earlier 3,066 was per-file token counting, see `mapping.md`), converging
per-cell so that each cell's ruler-adjusted median-of-seeds
winner **beats the gfx900-spoof floor** (ties at ±5% = parity, and parity alone is not
the win the campaign is here for). ±5% is the standing success bar, but it is
narrower than the measured repeat noise (CV p90 27.8%, `results.md` §12.3), so a
±5% "parity" is not evidence of indistinguishability — grade with `ab_audit.py`
(±27.8%) when the claim matters. and lands as close to the `gfx90c_theoretical_limits.md`
ceiling for its (family, bound_class) as the machine will give. The whole campaign is
driven by `port_tensile.py --auto` (deterministic harvest → mutate ≤2 knobs → re-run).

Stated goal (from `tensiles_in_system_rocm.txt`): replicate and produce a
`tensilelibrary` that performs all of the shipped functions for gfx90c, performing
**better** than gfx900 spoofing. No more, no less.


**implementation_plan.md — Core Strategy phase counts (pre-trim)**
shipped `gfx900` footprint (28 families, 4 patterns = 418 phases:
SS 105 · DD 44 · HH 40 · HH_HPA 20 · HS_HPA 20 · CC 32 · ZZ 40 · legacy auto 117
— re-derived 2026-09-27: 410 + 8 legal ZZ replacements after the occupancy gate,
see `changelog.md`)

**implementation_plan.md — AI Must Not Decide (duplicate of tensile_tuning_context.md)**
**AI Must Not Decide**

`gfx90c identity / ISA legality / AsmCaps / compiler flags / runtime support /
correctness / measurement / accepted performance` — including in the manual-LLM
contingency. The model only proposes candidate *parameter vectors*; Tensile generates,
the compiler validates, the hardware decides, the DB remembers.


**implementation_plan.md — Correctness Gate (duplicate of tensile_tuning_context.md)**
**Correctness Gate**

Always: generate → correctness → benchmark. Never: benchmark → fast → maybe correct.
Wrong kernel = failed candidate. The validator must reject known-invalid configs
(no `AssertSizeMultiple: [1]`, no `SIA>1`, no Fp16AltImpl, LDS ≤ 64 KB/CU).


**implementation_plan.md — Reward Hacking (duplicate of tensile_tuning_context.md)**
**Reward Hacking**

Independent benchmark + fresh inputs + correctness validation + repeat runs + guard
checks + dtype-specific tolerance. Evaluator stays outside model control. No
max-of-seeds; median-of-seeds is the statistic.


**implementation_plan.md — Frozen baseline (pre-trim)**
**A. Frozen baseline (conclusions sourced from `prior_INSIGHTS_CAVEMAN_ULTRA.md`)**
- Port mechanics **DONE**: pristine Tensile + minimal in-tree gfx90c support
  (3 bookkeeping entries in `Tensile/{Common,AsmCaps}.py`); Phase-0 gates 10/10
  [OK]; anti-alias 0 gfx900 leak; synthesis PASS.
- Performance = **parity, not wins** on the only same-run pair (0 / 11 / 0 at ±5%).
  Candidate suite A–G gave **5W/10T/6L** over 21 shared cells.
- 6 genuinely-new problem cells were produced. Best measurements: FP32 1118.7 @1024³,
  FP16 2492.1 @4096³, BF16 1108.5 @2048³, FP64 98.6 @1024³, INT8 881.2 @2048³.


**implementation_plan.md — Replicated footprint (pre-trim)**
**B. The replicated footprint (mapping contract, see `mapping.md`)**
28 frozen families = 7 dtype/op sets × 4 contraction patterns:
`{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}` × `{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}`
= **2,285 distinct shipped kernels** (459+ distinct size-keys; the old 3,066 was
per-file token counting — see `mapping.md`). No gfx90c library ships anywhere today.
Reproduce the family matrix natively; per-family tile decks come from the mapped
gfx900 top-tiles + the measured prior winners (frozen conclusions); do NOT chase the
1,980-key size tables (defensive mesh, not a tuning result).


**implementation_plan.md — Technical findings 2026-09-19 (pre-trim)**
**Technical findings (2026-09-19)**

- **HS_HPA rejection root-caused.** Guard trace (`PrintSolutionRejectionReason`) +
  source audit (`potential_configs.md` §4): the rejection is stock-Tensile's non-MI
  assembly `GLVW==VW-or-1` generator guard (`SolutionStructs.py:4583-4596`),
  triggered by the pv-reduction in `setGlobalLoadVectorWidth` (`:2010-2047`) —
  isa-independent, not a gfx90c HW/ISA limit, not an assembler failure.
  Guard-legal HS_HPA parameterizations (MT64x64x16/TT4x4/VW4; MT64x64x8/TT4x4/VW2)
  are admitted 1/1 and assemble for gfx90c. HS_HPA tuning resumes on them.
- **Scheduler mirror gap — FIXED (2026-09-19):** `_validate_tensile_loads` now models
  the `GLVW==VW-or-1` predicate (scheduler.py `_validate_tensile_loads`), which the
  64x64x8 deck previously violated; 6 unit tests + 410/410 manifest sweep pass.

**implementation_plan.md — Driver Architecture spec, Stage 1–7 (pre-trim, now oto/runners docstrings)**
**The Driver Architecture**

**Stage 1 — Manifest & Phase Execution (port_tensile.py core)**
**Scope:** Read phases.yaml manifest, execute each phase via Tensile CLI, collect outputs.
**Key files:** phases.yaml (data-only manifest), TensileCreateLibrary/TensileBenchmark CLI.
**Mechanics:** For each manifest row, shell out to Tensile with dtype/shapes/ScheduleName/NumBenchmarks; collect 2_BenchmarkData/*.csv, library, telemetry; persist `json.dumps` payloads via SQLite `records` INSERT (knowledge_base.md §10).

**Stage 2 — Candidate Generation (scheduler.py + oto/ledger/agent.py)**
**Scope:** Emit candidate configs for benchmarking; occupancy-aware GSU/WGM/MT/TT sizing.
**Key files:** potential_configs.md (candidate deck), mapping.md (family decks).
**Mechanics:** From mapping.md family decks + harvested winners, mutate by ≤2 knobs (neighbour search); validate LDS fit on 64KB/CU, 7-CU occupancy ≥ floor, config-valid (no AssertSizeMultiple: [1]), fp unique.

**Stage 3 — Benchmark Execution (Tensile CLI via port_tensile.py)**
**Scope:** Run TensileBenchmark for each phase; detached+killable GPU processes.
**Key files:** TensileBenchmark client, configs/phaseN_*.yaml.
**Mechanics:** Setsid process groups; 's' kills current phase, 'q' quits; Ctrl+C kills in-flight benchmark group; EXIT trap stops telemetry idempotently; finite `--phase-timeout` default.

**Stage 4 — Adaptive Repeat / Convergence (stability gating & retirement)**
**Scope:** Always-on stability/retirement engine; median-of-seeds aggregation; adaptive repeat; retirement gating.
**Key files:** Suite v7 PHASE 26 block, PHASE 29 N8 median aggregation.
**Mechanics:**
- Per-cell aggregate: median-of-seeds (best-of-cell median is the winner metric;
  spread=(max−med)/med reported)
- Stability gate: CV ≤ 15% per cell (enforced in `agent.converged()`); the former
  `should_repeat`/`classify_stability` matrix helpers were removed 2026-09-25
- Tie band: ±5% (parity)
- Retirement: ≥2 independent runs/cell gating via `policy.check_retirement_eligibility`
  (single Tier-2 path); append action=retire records (append-only)

**Stage 5 — Analytics & Append-Only Registry**
**Scope:** APPEND-ONLY data registry; per-cell analytics; native-vs-spoof deltas; feed seeds to Stage 2, verdicts to Stage 6/7.
**Key files:** Suite v7 PHASE 29 block, oto/device/peaks.py (PEAK_GFLOPS), gfx90c_theoretical_limits.md (§5 ceilings).
**Mechanics:**
- Load raw records from 2_BenchmarkData/*.csv via oto/metrics/analytics.py/registry
- Per-cell analytics: winner via N8 median-of-seeds, spread ratio, CV, % of family-realistic ceiling (with decode DDR exemption), and cell-status classification (RED = missing contract cell, ORANGE = measured <50% ceiling, GREEN = at/above)
- Native-vs-spoof per-cell deltas: spoof arm = recalled `gfx900_ref_*` chain
  (cross-run, never re-run; `--resume` continuations fold in); withhold when no reference floor
- Append-only DB: sqlite3 `records` INSERT of `json.dumps` payloads; rows never edited/deleted
- Feed seeds to Stage 2, verdicts to Stage 6/7

**Stage 6 — Synthesis / Build (final HIP library)**
**Scope:** Build final HIP library from certified winners; anti-alias enforcement; regression gate.
**Key files:** Suite v7 PHASE 28 block, TensileCreateLibrary --merge-files.
**Mechanics:**
- Query Stage-5 certified winners from DB (median-of-seeds, ruler-adjusted)
- Group by 7 dtype/op × 4 contraction patterns → emit per-op 3_LibraryLogic/gfx90c_<Op>.yaml
- Schema-validate: len(data)>=9, fields per LibraryIO.py:232-249
- TensileCreateLibrary --architecture=gfx90c --merge-files → FINAL_LIB_DIR
- Anti-alias enforcement: scan every emitted/merged YAML + artifact for gfx900/vega10 tokens; reject build on ANY hit
- Regression gate: count check vs the pinned shipped-dat manifest (`gfx90c_results/gfx900_shipped_manifest.json`, 2,285 kernels re-derived 2026-09-25); FAIL+DB row on mismatch
- FLAG: gate deferred — build must consume only certified winners, never blind-union

**Stage 7 — Acceptance A/B & Final Report**
**Scope:** Per-cell native-vs-spoof A/B vs the recalled gfx900 floor; final per-family acceptance report.
**Key files:** `oto/tensile/library.py` (dat parse + manifest + `reference_chain`), `_compute_ab_verdicts`, oto/metrics/report.py.
**Mechanics:**
- Floor = dedicated `gfx900_ref_*` chain (ScheduleName "vega10"); `--gfx900-reference
  --resume` continues it, retrying failed phases once and reusing decided base phases
- Per-cell verdict = best-of-cell median per arm on `(family, dtype, shape)` (`cell_key`);
  delta_pct=(nat−spoof)/spoof; |Δ|≤5% TIE=parity
- Throttle variance ruled out via spread_ratio=(max−med)/med
- Cross-run pairs withheld; pairs split across base/resume are reconciled via the chain
- Acceptance REPORT: per-family coverage vs the pinned shipped-dat manifest (2,285 kernels); per-cell native-vs-spoof WIN/TIE/LOSS vs the **recalled gfx900 reference floor** (`gfx900_ref_*`, via `oto/tensile/library.py` + `_compute_ab_verdicts`); %-of-§5-ceiling per cell; RED (missing) / ORANGE (<50% ceiling) cell lists; overall PASS/FAIL


**implementation_plan.md — Design spec §1–3 (pre-trim, now oto/runners docstrings)**
**1. Design goal**
A **python driver** (`port_tensile.py`, single process) that:
1. holds a **data-only manifest** of phases — `phases.yaml`. Everything about a phase
   is DATA: id, label, dtype, shapes, `ScheduleName`, config-template, seed count;
2. runs each phase by shelling out to Tensile's existing CLI (client +
   `TensileCreateLibrary`) — the driver **never reimplements** benchmarking, config
   semantics, or result parsing;
3. collects Tensile's own outputs (`2_BenchmarkData/*.csv`, library, telemetry),
   persists **`json.dumps` payloads** via one `registry.append_record()` → SQLite
   `records` INSERT (knowledge_base.md §10);
4. analyses per-cell winner (median-of-seeds), %-of-theoretical (`gfx90c_theoretical_limits.md`),
   native-vs-spoof delta, adaptive-repeat (CV / top-2 gap);
5. **decides the next candidate set deterministically** — harvest wins, mutate
   winner-neighbours by ≤2 knobs, append config rows to `phases.yaml`;
6. terminates on convergence (no RED cells under threshold, or budget spent), with
   cooldowns between GPU phases.

`--auto` = run 2↔5 repeatedly until 6, no human in the loop. Agent harvest/accept
(round-N candidates) and convergence + retirement finalize are two small modules
plugged into the loop, not more hand-scrolled blocks.

**2. Do-not-reinvent rule (verbatim from the user voice)**
> Never solve a known-solved basic problem on our own for zero reason. If the OS, the
> Python stdlib, or Tensile already solves it, use that.

The driver uses only existing solvers:

| Concern | Implementation | Solver that already exists |
|---|---|---|
| Phase list | `phases.yaml` = data | data file |
| Round-trip one phase | `for ph in manifest: run(ph)` | Python |
| Ledger records | `json.dumps(dict)` in SQLite `records.data` | stdlib `json` + `sqlite3` |
| Concurrency safety | one writer process; WAL; INSERT-only `records` | stdlib `sqlite3` |
| Run/skip decisions | `policy.should_run(phase, fp) -> bool` + unit tests | Python |
| Analysis + report | `oto/metrics/analytics.py` / `oto/metrics/report.py` modules | stdlib `csv`, `statistics` |
| Telemetry | python `pathlib` sysfs reads | kernel sysfs |
| Peak authority | `from oto.device.peaks import PEAK_GFLOPS` | existing module |
| CLI | `argparse` + one `port_tensile.yaml` | stdlib `argparse` |
| Manifest order asserts | python `assert`/`pytest` on manifest order | pytest |
| Error trail | top-level try/except → one record | python |

**3. Module list (numbered, ordered)**
1. **Manifest first.** Write `phases.yaml` from the phase table captured in
   `potential_configs.md` / `mapping.md` (mechanical transcription). A test asserts
   manifest order matches the documented order **during migration only**.
2. **`oto/ledger/registry.py`** — one `append_record()` (sqlite3 INSERT), one `read_records()`
   iterator, queries `phase_retired`, `config_retired(phase,fp)`,
   `first_benchmarked(phase,fp)`. Never UPDATE/DELETE `records`. `phases.yaml`
   stays the manifest (a `phases` table is not the source of truth).
3. **`oto/metrics/report.py`** — renders the per-run/per-cell report → `write_report(...)`.
4. **`oto/metrics/analytics.py`** — adaptive CV/top-2 scan, winner synthesis, per-cell delta,
   ceiling util vs `gfx90c_theoretical_limits.md`.
5. **`oto/metrics/policy.py`** — `should_run(phase, fp)` in order: scope check → tier-1 retired
   (fp-less) → tier-2 retired (phase,fp) → identical-fp skip (opt-in). Unit-test the
   matrix (mirror of the prior policy cases).
6. **`scheduler.py` + `oto/ledger/agent.py`** — cooldown latch (first-GPU-phase exempt),
    `--targets`/`--family`/`--pattern`/`--shape` scope, adaptive NumBenchmarks bump,
    **occupancy-aware GSU/WGM sizing**;
   `oto/ledger/agent.py` reads `oto/metrics/report.py` → harvest / mutate (≤2 knobs) / tie → append rows →
   return subset to re-run.
7. **`port_tensile.py`** — preflight (arch, device, tensileness); per-manifest-row run
   Tensile, collect, register, cooldown; at end write report; `--auto` loops 2↔6 until
   convergence or budget. Replaces the special frozen-block handling.
8. **`--arch gfx90c`** is emitted into every Tensile invocation (fixed target — not
    a driver flag); the spoof floor baseline = the dedicated `gfx900_ref_*` chain.
9. **Entrypoint.** The python driver is the only suite entrypoint.
10. **Fold the redundant tooling** — favouring counters and fingerprint helpers
    all become python modules or tests.


**implementation_plan.md — Design spec §5 (pre-trim)**
**5. Phase 5 / 6 / `--auto` mapping**
- **Agent harvest/accept round-N candidates** (`agent.harvest()`): cells with native
  median ≥ spoof median (ruler-adjusted) → incumbent; RED/non-converged cells →
  `candidates.spawn_neighbours(winner, ≤2 knobs, occupancy-aware)` appended to
  `phases.yaml`.
- **Convergence + retirement finalize** (`agent.converged()`): no below-ceiling cells,
  ≥3 configs/cell, ≥2 runs/cell, CV ≤ 15% → write tier-2 retirement records (≥2
  independent runs/cell gating) and stop. Budget exhaustion returns converged=False and
  a FAIL readout, not a pass.
- **`--auto`**: `for _ in range(budget): run(manifest); write_report; if
  agent.converged(): break; agent.feed(manifest)`.


**implementation_plan.md — Design spec §7 (pre-trim)**
**7. Statistics/HTML tooling (oto/metrics/report.py pipeline)**
The reporting surface is `oto/metrics/analytics.py` → `oto/metrics/report.py` → `acceptance_report.json` +
self-contained `acceptance_report.html` (single-file dashboard, Carbon design
language). The driver feeds an append-only data layout (per `knowledge_base.md` §10):
- `gfx90c_runs/run_YYYYMMDD_HHMMSS/` with `configs/phase<N>_*.yaml`,
  `phase<N>_*/2_BenchmarkData/*.csv`, `logs/telemetry.csv` (header-in-file),
- `gfx90c_results/registry.db` (`records` INSERT-only) as the canonical ledger,
- `gfx90c_results/acceptance_report.json/.html` regenerated per run (and on
  `'e'`/`'q'` early exit), plus any jsonl `export` of new rows.
Any module that changes these outputs must be validated by re-running the pipeline
before merging.

**implementation_plan.md — Triaged fixes (pre-trim, 2026-09-27)**
**Triaged fixes (self-contained dispositions)**

**P0 for oto (all four in scope)**
1. **Deterministic driver (`port_tensile.py`)** per the architecture above.
2. **Finite per-phase timeout default** — `--phase-timeout` default is finite
   (generic runaway protection) and per-phase skippable/killable.
3. **Interactive single-phase kill** — 's' skip / 'q' quit exactly one phase, not
   Ctrl+C-the-whole-run.
4. **Auto-retire trust gating** — the 3 existing `retire` records came from a single
   invocation; under 77% winner instability, require **≥2 independent runs** per
   trusted shared cell (incomplete_work §4.6).
5. **Peak-table prose drift** — stale prose still claims BF16/INT8 = 3226. gfx90c is
   single-rate (1613). `oto.device.peaks.PEAK_GFLOPS` is the single source; regenerate
   dependent artifacts.

**Known-fixed states (do not regress)**
| Finding | Correct form |
|---|---|
| Ruler shape strings `"MxNxK"` vs dataset `"MxNxB"+SizeL` | `oto/device/peaks.py` rulers + `bound_class()` |
| `adj_cells()` no-op (dt key not `(dt,cls)`) | keyed `(dt,cls)`; missing = None |
| geo-mean fallback inferring missing rulers | removed; missing reported |
| Phantom `("BF16","DDR")` ruler → nonexistent phase | deleted |
| report dtype `extract_dtype_from_phase_id` | restored via token-based family parse (oto/metrics/report.py; legacy regex produced 'unknown') |
| `AssertSizeMultiple: [1]` crash (scalar int vs dict) | `[{}]`/fixed keys: config-validation gate |
| Toolchain — `hipconfig --version` on stderr | try/except + explicit ROCM_PATH |
| HardwareMonitor `stoi` on APU | `HardwareMonitor: False` in configs |
| Telemetry `.hdr` sidecar, kHz/mW units, parent-dir glob | header-in-CSV, canonical units, `hwmon[0-9]*` |
| joblib/loky vs Python 3.14 resource-tracer | **solve not avoid** (pin/fix parallelism; fallback `CpuThreads: 1` documented) |
| Self-terminating run (no new bench work) | prove the run will execute something before starting |
| Orphaned subprocess fragilities on abrupt breaks | `|| true`, `set +e`-style isolation (python makes it moot) |
| Acceptance native arm scoped to one run → all-zero report | whole-db arm (`_native_records_all_runs` / `_native_analytics_all_runs`); winners may come from an older run |
| A/B delta from max raw sample while columns showed medians | all stats per-kernel-median-first; kernel medians keyed by (run, phase, fp) |
| A/B columns hard-wired to one basis, re-breaking the delta | columns render `native_value`/`spoof_value` (the operands actually divided) under basis-aware headers |
| Occupancy gate unable to fire (no `MacroTile`, no VGPR count) | `oto.tensile.gates.occupancy.occupancy_feasible`; `validate_config` + `_estimate_occupancy` both delegate |

**Open defects (triaged 2026-09-27, resume/candidate evidence)**
1. **`_write_phase_config` early-returns without writing the file.**
   `execute_phase` ignores the return, so Tensile is launched against a config that
   was never written → `FileNotFoundError`, rc=1. This is the entire 121-phase
   rc=1 bucket of `gfx900_ref_20260926_201843_resume` (1,091 configs exist for 1,212
   targets; the 121 missing are exactly the rc=1 set). Fix both ends: treat a
   `None` return as a pre-flight rejection (record a skip, never spawn Tensile), and
   filter assembly-class-illegal configs out of reference-deck generation. Cost
   today: a wasted Tensile launch per phase and an unattributable failure bucket.
2. **ZZ/double native phases die on Occupancy limit — FIXED (preflight gate + deck revision).**
   All 8 executed `run_20260926_201835` phases ended `Generating kernel source resulted in error 4`
   = `overflowedResources == 4` = Occupancy limit (`Tensile/KernelWriterAssembly.py:15422`,
   `functionSuffix`). Distinct from the benign "error 3" note below. Root cause was a
   gate hole, not a bad tile choice: `CandidateGenerator._estimate_occupancy` inferred
   threads from `ThreadTile` with a `64 // tt` heuristic, **ignored `MacroTile`, and
   never counted VGPRs**, so it could never fire.
   Landed: `oto.tensile.gates.occupancy.occupancy_feasible` + `VGPR_PER_ELEMENT` / `VGPR_BUDGET`, wired
   into `validate_config` and `_estimate_occupancy`; fails closed on an unmodelled
   dtype (a wrong guess picks the wrong weight and would re-admit the failure).
   Verified: reproduces all 9 observed pass/fail cases, rejects exactly the 8 dead
   phases and nothing else in the pre-fix 410-phase deck, 18/18 tests
   (`test_occupancy_gate.py`). Deck 410 → 418: dead `128x64x8/8x4` + `64x128x8/4x8`
   replaced by legal `128x32x8/8x4` + `32x128x8/2x8`, plus new-axis `64x64x8/4x2` and
   `128x32x16/8x4`, all × 4 contraction patterns. Full derivation, the calibrated
   weight table, and the pre-fix deck proof live in `potential_configs.md` §5.7 —
   that section is the authoritative home, not this entry. ZZ is now **legal but
   unbenchmarked**: the next real step is a TTY run, not more code.

**CPU-only work queued (no GPU, ordered by value)**
These are the only remaining items that do **not** need a TTY. Everything else in
the route portfolio is measurement-bound (`potential_configs.md` §8.2).

**Status 2026-10-09 — all six items complete:**

1. ✅ **Measure real per-thread VGPRs** — `oto/harness/measure_vgprs.py`
   (llvm-readelf on Tensile's emitted assembly `.o` metadata, corpus-wide,
   CPU-only). Measured medians per (dtype, TT) now in
   `scheduler.MEASURED_VGPR_BY_DTYPE`; invariant test
   (`test_occupancy_gate.py::TestMeasuredRule::test_corpus_measured_totals_agree_with_gate`)
   proves gate-legal ⇔ measured < 256 VGPRs. The occupancy model (§5.7) is now
   measurement-ratified, not calibrated.
2. ✅ **Set `PrintSolutionRejectionReason`** — already present in GlobalParameters
   (`port_tensile.py:1052`).
3. ✅ **Sweep the floor deck through `check_candidates.py`** — `--floor` mode:
   **all 30 per-cell floor winners pass all 4 gates**; whole-deck residue
   1 464/6 855 (21 %) is generator-rule artifacts on non-winners (GLVW/VW,
   assembly) + 72 genuine occupancy-LDS (never-won entries, gfx900-64K-LDS
   kernels the APU rejects).
4. ✅ **Fingerprint-diff native vs floor winners per cell** —
   `oto/harness/cell_knob_diff.py`: 30 cells shared, 22 native / 8 floor
   (SS:512/768/1365/2048, HH:1024/2048/4096, CC:256); CC:256 is the single
   outside-band LOSS and the only sanctioned steal.
5. ✅ **Occupancy margin in `check_candidates.py`** — `_occupancy_margin()`
   prints `wg/cu=N acc=…vgpr …% of 64K file`.
6. ✅ **Audit the 117 legacy auto phases** — 560 `phase_auto_*` dirs total; the
   auto pool wins 13/34 cells natively (38 %), incl. HH:256 763.4 and SS:1024
   1135.1 — **not marginal**; keep them (rename S/Z tokens at hygiene time).

Full write-up: `gfx90c_tuning_guide.md` (the tuning cookbook).

**Known hazards — must never regress**
- **APU wedge at sustained 2048³-style benchmarks** (HW-Exception, exit 134). Rule:
  cooldown + detached+killable GPU processes; no untimed marathon cells.

**Benign warnings (do not spend time on)**
- "Kernel file context manager opened without any kernel files" (MergeFiles: False).
- "error 3" overflowedResources on non-MFMA half kernels (upstream-declared fine).

**implementation_plan.md — Option H plan, banner through Hplan.6 (pre-trim)**
**Option H — Mutator overhaul (formalised, single-shot)**

> **Status: ALL FOUR PHASES LANDED (2026-10-05/06); nothing above is superseded.**
> `Hplan.3` (ledger + outcome), `Hplan.4` (legality), `Hplan.5` (coverage +
> fitness) and `Hplan.6` (synthesis, graded form) are implemented and green:
> - Phase 1: append-only `proposals` table + ledger/novelty API (`oto/ledger/registry.py`),
>   `oto/ledger/mutator.py` (classifier, novelty, negative cache, per-run overlay), the
>   `agent.mutate_and_feed` rewrite that routes candidates to the overlay instead
>   of `phases.yaml`, and `analytics.count_benchmark_rows` as the single owner of
>   CSV shape.
> - Phase 2: `legality.py` manifest-derived legal domains — reject set never
>   proposed (measured legal rate 100%, `proposal.md` §H.7 criterion 3).
> - Phase 3: `coverage.py` per-cell states (none / unstable / retired) +
>   lower-confidence-bound parent selection.
> - Phase 4: `synthesis.py` coverage-guided sampling with graded multi-shape
>   sweeps; the lattice remains only as a *reported* fallback.
>
> Two behaviours deliberately did **not** change, and both would have been easy to
> get wrong:
> - **The identical-fp skip is bypassed for the mutation arm only while the ledger
>   is available *and* the outcome signal is wired** — `ConvergenceAgent.skip_mutation_arm()`
>   flips back on the moment `mutator.ledger_available()` fails, so a missing ledger
>   re-enables the skip instead of silently re-emitting ungraded candidates.
> - **`phases.yaml` stays curated.** Candidates go to the per-run overlay
>   (`mutator.write_overlay`); the runner merges only that run's overlay. Discarding
>   a bad batch deletes a file, not history.
>
> `scheduler.mutate_winner` was still the lattice sampler at Phase 1 — Phase 1
> replaces the loop's memory, not its generator. Phase 2 replaced the sampler with
> manifest-derived legal domains (`legality.sample_legal`), and Phase 4 made
> `synthesis.synthesize_cell` the configured sampler; the pre-Phase-1 path remains
> reachable for tests only.
>
> **Read `proposal.md` §H.1.2a and `changelog.md` (2026-10-05) before implementing Phase 1.**
> The evidence that originally ordered this plan — "mutants produced zero GFlops" — is
> **retracted**; it was an artefact of reading the `GFlops`-headed column, which is a problem
> index rather than a throughput. Through the canonical loader the mutants are productive but
> **ungraded**. The consequence for this plan is concrete: the negative cache's motivation in
> `Hplan.3` step 9 no longer has historical support, so it ships as a *forward* guarantee with
> a test that asserts it does **not** fire on today's corpus, and D5 (single-shape, ungradable)
> is promoted to co-equal status with D6. H.3.8's definition is unchanged and still correct —
> it is the historical justification that was wrong, not the predicate.
>
> Option H is **APPROVED (2026-10-09)** — the user answered §H.10's decision
> question in full ("proposal.md is approved, so Option H is approved"): all four
> phases are implemented and CPU-tested, and the go-ahead for a GPU-backed run of
> the mutation arm is granted. The evidence and design rationale live in
> `proposal.md` (addendum dated 2026-10-05); **this section is the executable
> plan only** and holds no restatement of its numbers — per §3 (one fact, one
> canonical home) and per the never-transcribe-a-count rule (§5), every figure is
> cited to `proposal.md` §H.x and read live by the tools.
> With approval recorded, the supersession table above is **in force** as of
> 2026-10-09 (Hplan.6-sampled mutants go to the per-run overlay, `phases.yaml`
> stays curated). The two unchanged behaviours (ledger-gated skip bypass,
> mutation-free path = plain Stage-3, never `--auto`) are committed alongside.

**Supersession notice (read before Stage 2)**

This section, once approved, **supersedes three parts of this file**:

| location | current text | superseded by |
|---|---|---|
| Stage 2 mechanics; §5 bullet 1; flowchart Stage 2 | "mutate by ≤2 knobs (neighbour search)", "mutate ≤2 knobs" | `Hplan.6` sampling |
| Stage 2 mechanics; §5 bullet 1 | "Emit candidate configs to `phases.yaml`" | `Hplan.3` step 7 — per-run overlay |
| Stage 5 | "Feed seeds to Stage 2" | `Hplan.5` coverage/fitness view |

Until approval, the code and this text remain consistent: `scheduler.mutate_winner`
still does ≤2-knob neighbour search and `agent.mutate_and_feed` still appends to
`phases.yaml`. Do not "fix" the code to match a future plan.

**Hplan.1 Defects this addresses**

D1–D6 as enumerated and evidenced in `proposal.md` §H.2. In plan terms:

1. **`--mutation-budget` does not bound anything.** `scheduler.py:379` consumes it in one
   boolean test (`if mutation_budget >= 2`). It gates two-knob pairs; single-knob mutants
   are emitted unconditionally. The flag's help text ("Maximum knobs to mutate per
   candidate") is therefore misleading.
2. **No novelty memory.** Iteration *n+1* re-proposes fingerprints already emitted.
3. **Output is largely non-functional.** `proposal.md` §H.1.2a measures this at the CSV
   layer with a same-run positive control. The loop has no field distinguishing "ran and
   produced nothing" from "worked".
4. **Mutants are written into the curated deck**, then skipped on the next pass.
5. **Mutants are single-shape**, so they are born ungradable against a multi-shape floor.
6. **Outcome is never recorded**, so the loop cannot learn from failure.

**Hplan.2 Deliverables**

| artefact | kind | owner doc |
|---|---|---|
| `oto/ledger/mutator.py` | new module: legality, novelty, coverage, outcome, synthesis | this section |
| `oto/ledger/registry.py` | `proposals` table + `json_extract` expression index | this section |
| `oto/ledger/agent.py` | `mutate_and_feed` delegates to `oto/ledger/mutator.py`; stops calling `append_to_phases` | this section |
| `scheduler.py` | lattice retained as a fallback sampler; `mutate_winner` unchanged | this section |
| `ab_audit.py` | report `origin` split, per-cell `n`/spread, outcome histogram | this section |
| `tests/test_mutator.py`, `tests/test_proposals_ledger.py` | new tests | this section |

**No new parser.** Every read of a phase's knobs, a CSV, or a fingerprint goes through the
canonical loaders already mandated by `claude.md` §2.1 (`tensile_library`, `analytics`,
`registry`, `all_runs.py`, `check_candidates.py`). If a needed value cannot be obtained from
them, that is a defect in one of them — fix it there, do not add a parallel reader.

**Hplan.3 Phase 1 — ledger + outcome (do this first; the rest is worthless without it)**

Rationale: this is the phase that makes the mutator a search rather than a dedup cache,
and it is independently useful even if nothing later is approved.

1. **PoC in `/tmp/opencode/`** (`claude.md` §5): a `proposals` table created against a
   **copy** of the live registry, with INSERT and the single monotonic
   `outcome` write-back, exercised end to end before any repo edit.
2. **Schema** exactly as `proposal.md` §H.3.1, including `origin`, `outcome`, and
   `build_class`. Migration is additive (`CREATE TABLE IF NOT EXISTS`); it must not touch
   the `records` schema or rewrite any existing row.
3. **Append-only discipline** (`knowledge_base.md` §10): rows are never `DELETE`d and never
   rewritten; `outcome` only advances `pending → terminal`. A single monotonic status
   column is not a mutation of history. Enforce with a trigger or an `UPDATE ... WHERE
   outcome='pending'` guard plus a test that a second write-back is a no-op.
4. **Novelty query**: novel iff `fp` absent from **both** `proposals` and the registry's
   decided set. Add the `json_extract(data,'$.fp')` expression index; do **not** change
   `has_fp_passed` semantics, only its cost.
5. **Outcome classifier** (pure function, CPU-only): reads a phase's
   `2_BenchmarkData/*.csv` via the canonical loader `analytics.load_benchmark_csv` and returns
   one of `functional` / `non_functional` / `legal_rejected` / `legal_slow`. `functional` iff
   that loader yields at least one record; `WinnerFreq` recorded alongside.
   **Implementation constraint, non-negotiable:** the predicate must be expressed *in terms of
   the loader*, never by re-reading the CSV and indexing the `GFlops` column. That column is a
   problem index, not a throughput — deriving the predicate from it is precisely the error
   retracted above. If the classifier needs something the loader does not expose (row count, to
   separate "rows present but all zero" from "no rows"), that accessor is added to
   `oto/metrics/analytics.py` as the single owner of CSV shape, not reimplemented here.
6. **Durability regression** (`proposal.md` §H.3.2): on a DB **copy**, delete every native
   row and assert the ledger and novelty still hold. Never run this against the live DB.
7. **Overlay** (step 7 above): candidates route to a per-run overlay the runner reads
   and the curator never sees. `phases.yaml` stays curated and reviewable; discarding a bad
   batch deletes an overlay, never edits history.
8. **Wire the mutation arm** to emit through `oto/ledger/mutator.py`, bypassing
   `opt_in_identical_skip` **only because** novelty is now structural. If this table is
   ever disabled or lost, the skip must be re-enabled for the mutation arm — the bypass is
   a correctness dependency on the ledger, not an optimisation.
9. **Negative cache**: if *k* consecutive candidates from one neighbourhood return
   `non_functional`, down-weight that neighbourhood instead of re-sampling it. *k* is a
   named parameter with a default, not a literal buried in code.
   **The historical justification for this is retracted** (see the status note above): replayed
   against today's corpus the cache correctly never fires, because every measured mutant row is
   non-zero. It therefore ships as a *forward* guarantee, and the test asserts both halves —
   it fires on *k* consecutive `non_functional` outcomes, and it does **not** fire when replayed
   over the archived runs. A test that only checks the first half would pass while the cache
   silently misfires on real data.
10. **Guardrail compliance to assert in tests**: no corpus count is transcribed into code,
    a comment, or a test fixture; counts are read live from the registry/manifest exactly
    as `auto_prompt._read_counts()` already does. No test asserts a literal corpus size.
11. **Revert the skip-bypass claim if phase 1 lands partially.** If the ledger ships
    without outcome, the mutation arm must keep the skip on, because a novelty-only ledger
    over a non-functional search makes the run *look* productive while measuring nothing.

**Phase 1 integration pass — LANDED (2026-10-06)**

The ledger shipped in Phase 1 with every one of the pieces above present and **none of them
reached a run**. Each gap is listed with the failure it produced, because each was silent:

| gap | what it actually did |
|---|---|
| overlay never merged | candidates were emitted and recorded, then never scheduled — the arm reported progress while measuring nothing |
| `run_id` dropped on emission | every proposal had `run_id=NULL`; "which run produced this" was unanswerable |
| proposal + phase = two commits | a crash between them left a permanently-`pending` candidate: its `n` never grows, so the cell is re-routed to `replicate` forever, indistinguishable from genuine instability |
| `resolve_phase_dir` never called | outcomes were never written back, so the ledger only ever grew `pending` rows |
| `WinnerFreq` via a private reader | a second set of Tensile CSV format assumptions; fails as zeros, which reads as "no kernel won" |
| `WinnerFreq` not persisted | H.3.8's evidence requirement was met only in memory, for the life of one process |
| negative cache process-local | every restart reported a saturated neighbourhood as untouched — the cache silently switched off at exactly the moment it was needed |
| `skip_mutation_arm()` never consulted | the bypass was computed on every emission and then ignored by the loop that skips |

**Schema decision — `proposal_observations`.** H.3.8 wants WinnerFreq "recorded alongside the
verdict". It cannot live on the `proposals` row: a proposal's *evidence* is re-observable while
its *verdict* is decided once, so columns there would invite overwriting the basis of a
decision already made. It is a separate append-only table, one row per observation, written
**before** the verdict — a crash between them leaves recoverable evidence and a `pending` row,
whereas the reverse order leaves a decided verdict with nothing behind it.

**Read-only registries.** Found while verifying: `SQLiteRegistry.__init__` ran the additive
schema migration unconditionally, so every `ab_audit` run rewrote the live floor registry's
bytes. No row was touched, but a report had changed its own subject. `SQLiteRegistry(base,
read_only=True)` now skips `_init_db` and every mutating method raises `PermissionError`; the
audit opens the registry read-only. Asserted byte-for-byte.

**Bypass scoping.** The identical-fp bypass applies to **overlay phases only**, and only while
`skip_mutation_arm()` is False. Applying it deck-wide would re-benchmark settled curated phases
every run, which is the opposite of what the skip is for.

**`tests/test_phase1_integration.py`** (53 cases) covers all of it by driving the driver's
`run_phases` loop, not the helpers in isolation — testing `_resolve_proposal_outcome` and
`should_run` directly passes even when the loop calls neither, which is exactly the state
Phase 1 was in. Verified by disabling the merge and the write-back: 2 of the loop tests fail.

**Hplan.4 Phase 2 — legality prior**

1. **Do not model the reject set; read it.** The reject predicates are already documented
   with source citations in `proposal.md` §H.2 and verified against the Tensile checkout
   at `e8a8999e`. Re-verify each one at implementation time and record the commit in the
   module docstring — the audit that seeded them is dated, and one of its five root causes
   was already found to mis-state its own condition.
2. **Sample legal-by-construction**: draw each knob only from values observed for that
   `(family, dtype)` in `gfx90c_results/gfx900_shipped_manifest.json` via the canonical
   parser. This is what removes the ±1-neighbour reject classes structurally rather than
   filtering them afterwards.
3. **Hard walls**: encode the verified half-precision `VectorWidth` floors (including the
   GSU case) and the MT/schedule rejections as named predicates with unit tests. Do not
   encode the audit's prose summary; encode the code.
4. **Keep `validate_config` as an assertion, not the search.** A candidate it rejects is
   recorded `legal_rejected` with its `build_class` so phase 1's negative cache can learn
   from the rejection.
5. **Legality is not the agent's judgement** (`AI Must Not Decide`): every predicate
   traces to Tensile source or the shipped manifest, never to model reasoning.
6. **Report the legal rate** from a CPU-only sampler sweep, with the baseline read live —
   never a transcribed percentage.

**Phase 2 outcome — LANDED (`legality.py`, 2026-10-05)**

| step | status | evidence |
|---|---|---|
| 1 read, don't model | done | every predicate re-read at `e8a8999e`; commit recorded in the module docstring and in `legality.TENSILE_COMMIT` |
| 2 legal-by-construction | done | `shipped_support` / `sample_legal`; knob values come only from the pinned manifest |
| 3 hard walls | done | `half_vector_width_floor`, `mt_has_shipped_schedule`; GSU case recorded in `DEFERRED_RULES` instead of guessed (below) |
| 4 assertion retained | done | `validate_config` still runs per candidate; rejections recorded `legal_rejected` |
| 5 not the agent's judgement | done | each predicate cites Tensile source or the manifest |
| 6 live legal rate | done | below |

**Measured (rerun `/tmp/opencode/legality_compare.py`; both arms same 29 curated
parents, same process, same `validate_config`):**

| family | lattice | prior |
|---|---|---|
| CC | 13% | 100% |
| DD | 58% | 88% |
| HH | 25% | 72% |
| HH_HPA | 24% | 91% |
| HS_HPA | 23% | 79% |
| SS | 55% | 70% |
| ZZ | 32% | 100% |
| **all** | **417 / 1169 = 35.7%** | **198 / 232 = 85.3%** |

The lattice column reproduces the D3 table exactly when re-run live (1169 proposed,
417 legal), which is the cross-check that the prior is measured against the same
reject model D3 was. The prior's residual is dominated by occupancy/register-file
and by load divisibility on the *full problem instance* — gates that need the phase's
sizes, not just the kernel, and which step 4 assigns to the assertion. Driving those
into the sampler would mean re-implementing the assertion, so they were left there.

**Three findings from implementing it, all corrections rather than confirmations:**

1. The audit's `A_half_VW1_assembly` label implied one wall; it is two conditions in
   different places, and the GSU one is *not* enforceable from our config surface. A
   first cut modelled it as `VectorAtomicWidth < 2 -> reject` and a live sweep showed
   it firing on shipped HS_HPA `GlobalSplitU` 2/3/5/7 vectors — 90 false rejections,
   i.e. exactly the "modelling the reject set" failure step 1 forbids. The real value
   is *derived* (`SolutionStructs.py:3574/3588`) and the guard is gated on the internal
   `_GlobalAccumulation`, so it now sits in `DEFERRED_RULES` with its reason. The
   reachable GSU rules were already `assembly_class_valid`'s (rules 2 and 3).
2. The half `VectorWidth` wall was **dead on arrival**. `EnableMatrixInstruction`
   (`:1918-1930`) tests `len(ThreadTile) == 2`, but our configs carry ThreadTile as the
   string `"8x4"`, whose length is 3 — so every candidate read as *undetermined*, the
   `is False` branch never ran, and the sweep reported a suspicious 100% accepted with
   zero drops. Fixed by normalising ThreadTile; the wall then caught the 32 shipped
   half `VW1` vectors. A legal-rate sweep that reports a perfect score is a bug report.
3. GlobalLoadVectorWidth is a function of MacroTile, so `schedule` and `loads` are not
   independent groups — moving them separately manufactured the indivisible-tile
   rejections the prior exists to avoid (85 of 86 HH_HPA rejects). They are now one
   atomic `tile` group. Separately, the base must be a *complete* shipped vector:
   deck/winner configs carry only MacroTile + ThreadTile, and building on those directly
   emitted configs with no WorkGroup, no VectorWidth and no load widths, which was the
   largest remaining reject cause. The parent now selects a neighbourhood (donors
   sharing its MacroTile); a shipped vector supplies the config.

**Hplan.5 Phase 3 — coverage + fitness**

1. Coverage view over `proposals` + `records` per `(family, shape)`: distinct `fp` count,
   sample count `n`, median, spread. Cells are targeted, not enumerated.
2. Three states kept distinct: no candidate → explore; `n = 1` or spread beyond the
   acceptance band → replicate; all-`non_functional` → retired, not "empty" (§H.1.2a).
3. Parent selection by **lower confidence bound**, never raw winner. Today's `harvest()`
   picks the winner, which is how a noise-level win becomes the parent of the next batch.
4. `ab_audit.py` surfaces `n`, spread, and the `novel`/`replicate` split so a replicate's
   value is visible after the fact.

**Phase 3 outcome — LANDED (`coverage.py`, 2026-10-05)**

| step | status | evidence |
|---|---|---|
| 1 coverage view | done | `coverage.coverage_cells`; `registry.all_proposals` + `coverage.samples_by_fingerprint` |
| 2 three states | done | `decide_state`; exactly three states, no fourth ("empty") |
| 3 LCB parent | done | `coverage.select_parent`, `agent.harvest(parent_by="lcb")` |
| 4 ab_audit surfaces it | done | `_proposal_coverage` + `_print_proposal_coverage` |

**Design points worth stating, because each is a place the obvious version is wrong:**

- **The band is read, never written** — and was initially *not read at all*. The
  first `coverage.measured_band_pct()` called `ab_audit.reproducible_band` with one
  argument for a two-argument function, and its `except Exception` turned the
  resulting `TypeError` into `None`. Every cell therefore ran with "no band",
  silently, while this document claimed the band was measured. Fixed by extracting
  `ab_audit.arm_record_sets` + `ab_audit.measured_band`, which are the *same two
  calls `audit()` makes*, so coverage and the audit cannot disagree and
  `_proposal_coverage` can pass the band it already has instead of recursing into
  `audit()`. Measured on the current corpus: **18.29%** (`max(cross-arm 18.29,
  repeat-tail, shipped-floor 5%)`) — the shipped 5% is a floor, not the answer.
  The test that let this through was `assertTrue(value is None or value > 0)`,
  which passes for a function that always raises; it is now four assertions that
  all fail when the read is stubbed back to `None`.
- **Explicit target cells.** `coverage_cells(..., target_cells=...)` emits a cell
  that was targeted but never proposed for, so it can be reported as `STATE_EXPLORE`.
  Deriving cells only from proposals made "we never looked" and "not on the list"
  the same absence — the conflation §H.1.2a is about.
- **`min_n` is the *worst* measured config in the cell, not the mean.** A cell whose
  best config has eight seeds and whose other config has one is not confidently
  measured; averaging that away is how a noise-level win becomes a verdict.
- **Retirement is checked after evidence exists.** `decide_state` returns `explore` for a
  cell with no decided rows before it can ever return `retired`, so "never tried" is
  never recorded as "tried and failed". `legal_rejected` also does not retire a cell: a
  rejected proposal never ran.
- **`n = 1` degrades the bound to the median rather than faking a variance.** Thin
  evidence is reported as thin (`min_n`, state `replicate`); a one-sample LCB that
  claimed precision would be a second definition of confidence.
- **The seeds travel with `CellAnalytics`** (`analytics.compute_cell_analytics` now
  attaches them). An LCB cannot be recovered from a median, a CV and a count, so parent
  selection would otherwise need a second read of every CSV. Hand-built cells without
  seeds degrade to the median rather than raising.
- **`parent_by="median"` remains reachable**, and `selected_by_lcb` /
  `parent_by` / `parent_score` are recorded on every winner, so a run's parent
  policy is visible afterwards and the two rules can be compared on the same data.

**Hplan.6 Phase 4 — synthesis, graded form**

1. Coverage-guided constrained sampling replaces the lattice walk; the lattice remains
   available as a deterministic fallback so behaviour degrades rather than failing.
2. Extend beyond the six knobs the lattice touches, using manifest-legal values only.
3. Emit multi-shape family-sweep candidates so a mutant can be graded (`Hplan.1` item 5).
4. Re-derive `ThreadTile`/`WorkGroup` from `MacroTile` the way `_reconcile_knobs` does, so
   the product constraint holds by construction.

**Status: landed.** `synthesis.py`; 79 tests in `tests/test_synthesis_phase4.py`. Notable
decisions, and what forced them:

- **Item 2 was already satisfied by Phase 2, and the knob budget is exhausted.**
  `legality.KNOB_GROUPS` covers all eight structural knobs the shipped solutions encode
  (`MacroTile`, `ThreadTile`, `WorkGroup`, `VectorWidth`, `GlobalLoadVectorWidthA/B`,
  `GlobalSplitU`, `DepthU`), plus `af0em` riding with the split group. The one remaining
  parsed knob, `grvw`, is deliberately excluded: it is not a Tensile parameter, and
  `BenchmarkStructs` calls `printExit()` on unrecognised names. So "extend beyond the
  lattice's six" is met by covering every legal knob, not by inventing parameters.
- **`TEMPLATE_KEYS` moved to `legality.py`** and is re-exported by `oto/ledger/mutator.py`. It was
  defined in `mutator`, but it names the keys `legality` *assembles*, so the definition
  belongs with the module that produces them; two copies would be two answers to one
  question.
- **The band is resolved lazily via `ConvergenceAgent.band()`, never in `__init__`.**
  `ab_audit.arm_record_sets` constructs an agent to manage phases, and
  `coverage.measured_band_pct` calls `arm_record_sets` — so computing the band at
  construction time is a cycle that ends by exhausting the stack. It was caught by
  `TestMeasuredBand` hanging rather than failing; `BandResolutionTests` now pins it. Note
  that a band of 5.0 on an empty corpus is `TIE_BAND_PCT`, the documented shipped floor,
  not an invented measurement.
- **The ledger's single `shape` column keeps the cell identity; the sweep goes in phase
  data.** Coverage joins on `(family, shape)`, so recording the sweep's first shape would
  re-file the candidate into a different cell and make the coverage joins wrong.
- **`retired` cells are skipped, not sampled.** Every candidate in such a cell was
  non-functional; re-drawing the neighbourhood is what the negative cache exists to stop.
- **Two latent bugs were found by the new tests and fixed.** `reconcile_tile` returned
  early on a *missing* `ThreadTile`/`WorkGroup` — the exact case it exists to solve — and
  an unsolved dimension rendered as the literal string `"None"`, which Tensile would
  reject at parameter-parse time rather than at our own check.
- **The lattice fallback is reported, never silent.** A run that quietly falls back looks
  identical to one that did not. `last_emission_stats` now carries `retired_cells`,
  `lattice_fallback_cells`, `ungraded_cells`, `graded_cells`, and `band_pct`.
- **`DepthU` travels with the tile, and crossing pairs are pruned against the shipped
  manifest.** The shipped manifest stores DepthU as the K component of the MacroTile —
  Tensile's `128x32x16` *is* "MacroTile 128x32 at DepthU 16" — so moving DepthU on its own
  manufactured exactly the occupancy rejections the scheduler's model then misread (16 of
  24 HS_HPA rejects in the first legality measurement). `DepthU` now rides with the `tile`
  group (`KNOB_GROUPS` is `tile`/`split`), and every emitted candidate's *cross-group* knob
  pairs are required to co-occur in some shipped solution (`legality.cooccurrence_check`,
  cached per family). This is co-occurrence read off the manifest, deliberately not a model
  of the reject set — the occupancy/assembly predicates still reject configs Tensile
  genuinely ships (verified: 31/135 shipped HS_HPA, 19/169 SS), which is why they are *not*
  hard walls. Measured consequence: the Phase-4 legal rate went 88% (176/200, HS_HPA 0%,
  HH_HPA declining entirely) to **100% (232/232) with all seven families proposing and zero
  false drops** (`/tmp/opencode/legality_p4.py`). The gate alone cannot reject a config
  Tensile ships — a shipped solution co-occurs with itself.


**implementation_plan.md — Hplan.8 (pre-trim)**
**Hplan.8 Sequencing and PoC gates**

Every phase is CPU-testable; **none requires GPU time**, and none may be validated by
running Tensile (`claude.md` §5: full benchmarks are TTY-and-user-only). Each module is
PoC'd in `/tmp/opencode/` before it lands, and no change lands without a PoC plus a scoped
parity check. Phase order is Phase 1 → 2 → 3 → 4; see `proposal.md` §H.9 for why that order.


**implementation_plan.md — Hplan.10 (pre-trim)**
**Hplan.10 Known gap found while formalising — `--auto` cannot currently disable mutation**

Recorded here because it blocks the "no mutations" run requested alongside this plan, and
because it is defect 1 of `Hplan.1` seen from the CLI.

Today **no flag turns mutation off**:

- `--mutation-budget 0` does **not** disable it. `scheduler.mutate_winner` emits
  single-knob mutants unconditionally; the budget only gates the two-knob block
  (`scheduler.py:379`). Zero yields a one-knob sweep, not no sweep.
- `--budget 1` does **not** avoid it either. The loop body runs the manifest, then
  evaluates convergence, then calls `mutate_and_feed` (`oto/ledger/agent.py:400`) — and only
  *then* increments the iteration counter and re-tests the budget. So a single-iteration
  `--auto` still harvests and mutates. (Since Phase 1 the candidates go to the per-run
  overlay, not `phases.yaml` — the original "polluting the curated deck" wording predates
  that and no longer applies.)
- `--stage` gates only the non-`--auto` branch (`port_tensile.py:3195`); it does not
  constrain `run_auto`.

The safe mutation-free path today is to **omit `--auto` entirely** and run the plain
Stage-3 path (`--stage 3`, or any of the `--family`/`--shape`/`--pattern` selectors),
which executes the deck once, updates run status, and regenerates the acceptance report
without entering the harvest/mutate loop. That is what `command.txt` now contains.

**Resolution (2026-10-05, user): withdrawn, not deferred.** Omitting `--auto` and using
the plain Stage-3 path is the intended and only mutation-free route, so there is no need
to give `--mutation-budget 0` the meaning "emit nothing" and no need to re-gate
`mutate_and_feed` on remaining budget. Those two behavioural changes are **not** planned
and no longer await approval. The defect that remains real is the one below, and Option H
addresses it at the source instead of via a flag.

The substantive gap Option H actually inherits: `--auto`'s only control over mutation
*width* is a flag whose help text overpromises. `mutate_winner`'s ≤2-knob lattice is
replaced by the manifest-legal sampler under `Hplan.6`, which bounds the search by
construction instead of by a flag that does not bound anything. `--mutation-budget` is
retained for compatibility and is expected to keep its current effective meaning (a
lower bound of 1 on knobs touched) until `Hplan.6` lands.

### results.md

**results.md — §9 resume failure triage (pre-trim)**
**9. Resume failure triage (404, `gfx900_ref_20260926_201843_resume`)**

| Bucket | n | rc | Root cause |
|---|---|---|---|
| Tensile `0 valid solutions` | 220 | 255 | Config rejected at solution enumeration. 154 `VectorWidth must be >= 2 for half`, 30 `ThreadTile not multiple of VectorWidth`, 25 GLVWA (VW4/1), 5 `totalElements 768 % (NumThreads*grvw) != 0`, 3 GLVWB, 1 GLVWA(VW8), 2 no reject line |
| Config never written | 121 | 1 | `_write_phase_config` returns early on the assembly-class gate **without writing the file**; `execute_phase` still launches Tensile on the missing path → `FileNotFoundError`. 1,091 configs exist for 1,212 targets; the 121 missing are exactly the rc=1 set |
| User skip (`'s'` keypress) | 63 | −1 | `skipped_by_user`. Not a config/hardware failure |

Family split: HS_HPA 204, SS 106, HH+HH_HPA 94. The doubled `phase_phase_*` config
naming is the consistent convention, not the fault.


**results.md — §10 acceptance-report mechanism (pre-trim)**
**10. Acceptance report — native arm re-armed to the whole database**

**Symptom.** `run_20260926_201835`'s report was uniformly zero: every family
`measured_cells=0 / best_median=0 / coverage=0`, `per_cell_verdicts=[]`, and all 38
deck cells RED/MISSING at 0.0.

**Cause — arm-scope asymmetry.** The spoof arm resolved across the whole reference
chain (1,881 cells), but the native arm read only the reported run. That run
executed only 8 non-duplicate phases (`402` were `identical_fp_already_passed`) and
**all 8 failed** with `Generating kernel source resulted in error 4`, which Tensile
maps to `overflowedResources == 4` = **Occupancy limit** in the ZZ/double assembly
kernel writer. Zero native cells in-run → empty analytics → deterministic zeros.
The real native winners were sitting in older runs the report never consulted.
**Fix.** The native arm is now the **whole database** — every `run_*` dir's CSVs plus
every registry `benchmark_result` row — so winners (including prior older winner runs)
are picked across all history, exactly as the spoof arm already was. Each verdict cites
the run/phase that produced the winning kernel.

**Delta semantics (corrected twice).**

*First bug.* The original code computed `delta_pct` from the cell's **max raw sample**
while the table displayed **medians** — the columns never reconciled (CC 192 displayed
31.4 vs 31.5, a −0.3% ratio, but reported −6.1% from underlying 40.49 vs 43.12). Every
statistic is now **per-kernel-median-first**, so a single lucky seed cannot decide a
verdict. Kernel medians are also keyed by source run, so the same
`(phase_id, fingerprint)` benchmarked by two runs is no longer pooled into one median.

*Second bug.* The two rendered columns were still hard-wired to "Best native median" /
"Spoof median" regardless of the basis in use, so switching basis re-broke the
guarantee. The columns now render `native_value` / `spoof_value` — the two operands
actually divided — under basis-aware headers, so the displayed ratio always equals the
printed delta (verified: 0 mismatches in JSON and in all 38 HTML rows, residual ≤0.44pp
= 1-decimal display rounding).

**Comparison bases** (`--native-agg`), per (family, dtype, shape) cell:

| agg | native vs | Question it answers |
|---|---|---|
| `winner` **(default)** | **best** vs **best** | does the deck's best kernel beat the floor's best kernel? (drop-in replacement) |
| `winner_clock` | best vs best, telemetry-adjusted | same, after normalizing each kernel to a common core clock |
| `median_clock` | median vs median, telemetry-adjusted | central tendency, clock-normalized |
| `floor_best` | native **median** vs floor **best** | can a *typical* native kernel beat the best kernel the floor ships? |
| `strict` | native **worst** vs floor **best** | does *every* native kernel beat the floor's best? (per-cell dominance) |
| `best_median` | native best vs floor **median** | lenient: deck winner vs a typical floor kernel |
| `median` | both medians | symmetric central tendency |
| `throttle` / `best` | sclk-stamped feed / max raw sample | legacy; `best` is seed-noisy, reference only |

**`winner` (best vs best) is the default** — it is the drop-in-replacement question:
you replace one shipped kernel with one native kernel, so the two candidates must be
each arm's best. Every statistic is per-kernel-median-first, so "best" means the best
*kernel* measured over its seeds, not the single luckiest seed.

**Telemetry adjustment (`*_clock` bases).** GFLOPS is linear in core clock, so each
kernel's median is scaled by `sclk_ref / sclk_measured`, where `sclk_measured` is that
phase's own sustained clock and `sclk_ref` is **one shared corpus-wide constant**
(1800 MHz, the highest clock the GPU held in this corpus) so neither arm is rescaled in
its own favour. Two guards make it refuse to lie:

1. **Idle floor is not a measurement.** A phase whose only busy samples sit at the
   400 MHz idle clock is dropped rather than scaled — scaling it by 1800/400 = 4.5x
   let a 20.7 GFLOPS kernel "win" a cell at 93.0 GFLOPS. Genuinely throttled phases
   (0.9-1.2 GHz, 158 of 770 in the resume run) are real and are kept.
2. **Coverage gate (`CLOCK_MIN_COVERAGE = 0.5`), applied symmetrically.** A clock-adjusted
   *best* is only comparable if drawn from the same population as the unadjusted best.
   At 9% coverage (the CC cells) the eligible subset is unrepresentative and its max sat
   52-67% below the unadjusted max, which flipped CC to native wins. Below the gate both
   arms fall back together to the unadjusted twin of the requested basis
   (`winner_clock` -> `winner`, `median_clock` -> `median`) and the cell is reported
   `clock_adjusted: false`.

**The native arm has no usable clock data, so `*_clock` is currently inert.**
`run_20260919_213727` (4,896 of the 6,790 native records) has **no telemetry file at
all**; `run_20260920_235815` has 458 rows, all at the 400 MHz idle clock, 0% busy and
from a sampler that predates per-phase tagging. Native clock coverage is therefore
**0.000 on all 38 cells**, and every `*_clock` run correctly degrades to its unadjusted
twin with a printed warning. The spoof arm is well covered (mean 0.74, 1,719 phases
tagged), so the machinery is real and verified — it simply cannot be applied
symmetrically until native is re-benchmarked by a sampler that tags `phase_id`
(`oto/metrics/telemetry.py` already writes it; `run_20260920_235815`'s file just predates that
change). Adjusting only the spoof arm would deflate the floor and flatter the deck, so
the gate forbids it.

The adjustment was verified against an independent recompute from the raw
`2_BenchmarkData` CSVs plus the telemetry timelines: **38/38 cells match** on both the
raw best per-kernel median and its clock-normalized twin.

**Assumption to keep in mind:** throughput ∝ core clock holds for ALU-bound kernels but
over-corrects memory-bound ones (GFM/GEMM small shapes are limited by mclk/DRAM), so a
clock-adjusted delta on a DDR-bound cell is an extrapolation. Both the adjusted and
unadjusted statistics are emitted per cell for exactly this reason.


**results.md — §11 why the preflight missed it (pre-trim)**
**Why the preflight missed it.** `oto.tensile.gates.occupancy._estimate_occupancy` derived the thread
count from `ThreadTile` via a `64 // tt` heuristic, ignored `MacroTile`, and never
counted VGPRs — so it returned ≥ 1 for every config and could never fire. The gap was
in the gate, not the tile choice.


### incomplete_work.md

**incomplete_work.md — orphan §4.2 mechanism line + §4.3–§4.13 (pre-trim)**
**Mechanism:** `port_tensile.py` + `phases.yaml` manifest + 7 modules (`registry.py`, `report.py`, `analytics.py`, `policy.py`, `scheduler.py`, `agent.py`, `gfx90c_common.py`) fully implemented and unit-tested. `--auto` convergence loop operational with deterministic mutate-≤2-knobs candidate generation.

**4.3 28-family native coverage (RESOLVED — 2026-09-13)**

**Mechanism (T3):** 28-family native coverage generated in `phases.yaml` spanning all 7 families `{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}` across 4   contraction patterns `{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}` with anchor problem shapes (304 candidate configs: 232 family + 72 auto; re-derived to **418 phases** 2026-09-27: 410 + 8 gate-legal ZZ replacements, see `changelog.md`.)

**4.4 Adaptive-repeat finalize (RESOLVED — 2026-09-13)**

**Mechanism:** Production adaptive repeat logic implemented in `port_tensile.py` (NumBenchmarks doubling for high-spread cells). Telemetry sampler in `telemetry.py` (`SysfsTelemetrySampler`) guarantees gated sample windows. *(2026-09-25: the `policy.py` `should_repeat`/`classify_stability` helpers were removed — stability is now a CV≤15% gate inside `agent.converged()`.)*

**4.5 auto-retire trust gate (RESOLVED — 2026-09-13)**

**Mechanism:** Implemented in `policy.py` (`check_retirement_eligibility`), gated on ≥2 independent runs/cell before emitting retirement decisions. *(2026-09-25: `classify_retirement_tier` and `apply_d2_4_protection` were removed — retirement is now the single Tier-2 path via `check_retirement_eligibility` + `should_run`/`is_config_retired`.)*

**4.6 Peak-table prose drift (RESOLVED — 2026-09-13)**

**Mechanism (T8):** Sourced strictly from `gfx90c_common.PEAK_GFLOPS` (single import point — BF16: 1613, INT8: 1613). All driver headers, analytics, and reports cite single-rate 1613.

**4.7 Synthesis evidence gate (RESOLVED — 2026-09-13)**

**Mechanism:** Implemented in `port_tensile.py` `synthesize_library()`. Emits per-family logic YAMLs, executes `TensileCreateLibrary --merge-files`, runs anti-alias scan rejecting any `gfx900`/`vega10` leaks, and verifies regression against 28 families.

**4.8 Occupancy = performance objective (RESOLVED — 2026-09-13)**

**Mechanism (T9):** `scheduler.py` candidate generator and `agent.py` convergence engine treat right-sized `GSU`/`WGM`/`MT`/`TT` as first-class objective knobs, scored against realistic ceilings in `gfx90c_theoretical_limits.md` §5.

**4.9 Driver Implementation & Remediation (RESOLVED — 2026-09-13)**

**Remediation audit completed and verified across all modules:**
- `port_tensile.py`: Added telemetry sampling (via `telemetry.py` `SysfsTelemetrySampler`, canonical units Hz/µW/mC/% logging to `logs/telemetry.csv`), interactive non-blocking `'s'` skip and `'q'` quit key listeners, fixed subprocess buffer deadlocks by piping to disk logs, fixed `run_ab_test` to query native (`ScheduleName="isa"`) and spoof (`ScheduleName="vega10"`) records separately, and implemented Stage 6 library synthesis with YAML logic generation, anti-alias scanning (`0` gfx900/vega10 leaks), and 2,285-kernel regression check (the earlier 3,066 was per-file token counting).
- `scheduler.py`: Fixed LDS usage calculation to `(M*K + N*K) * elem_size * NLCA / 1024.0`; fixed `parse_tensile_shape` to robustly handle batched (`_B16`) and explicit K (`_K4096`) shapes; improved wave-based occupancy estimation.
- `agent.py`: Upgraded `converged()` to evaluate full multi-condition convergence (≥2 independent runs, ≥3 distinct configs, ≤1% movement, and no RED cells); replaced hardcoded static fallback in `_reconstruct_config` with family-aware defaults.
- `registry.py`: Protected `append_phase` with `INSERT OR IGNORE` and duplicate checking.
- `policy.py` & `analytics.py`: Clean stdlib implementations using realistic ceilings from `gfx90c_theoretical_limits.md` §5.

**4.10 Ctrl+C signal handler + stale-run cleanup (RESOLVED — 2026-09-13)**

**Mechanism:**
- `_signal_handler` now calls `sys.exit(130)` after `os.killpg` + registry `update_run_status(interrupted)`.
- `registry.cleanup_stale_runs()` added (bulk UPDATE `started→interrupted`) and called in `TensileDriver.__init__` before creating new run dir.
- `run_phases()` marks run `interrupted` when `_stop_requested` is set.
- 3 orphaned runs (run_140507, run_141220, run_143006) corrected in live DB.

**4.11 Tensile Top-Level YAML Generator & Pipeline Robustness (RESOLVED — 2026-09-13)**

**Mechanism:**
- `port_tensile.py`: Fixed `_write_phase_config` to derive correct `TransposeA`/`TransposeB` per contraction pattern in label (`Ailk_Bljk` $\to$ NN/FF, `Ailk_Bjlk` $\to$ NT/FT, `Alik_Bljk` $\to$ TN/TF, `Alik_Bjlk` $\to$ TT/TT); mapped `MacroTile0`/`MacroTile1` properly from string representation; dynamically calculated `WorkGroup` tile ratios (`MacroTile0/ThreadTile0`, `MacroTile1/ThreadTile1`, 1); set proper HPA / `HS_HPA` mixed precision flags.
- `scheduler.py`: Added `MacroTile` / `ThreadTile` divisibility check (`MacroTile0 % ThreadTile0 == 0`) and valid thread count constraints ($64 \le \text{threads} \le 1024$, multiple of 64) in `validate_config`.
- `analytics.py`: Added whitespace-stripped parsing and per-kernel GFlops extraction in `load_benchmark_csv` to handle space-padded CSV headers emitted by Tensile.
- Verified across unit tests and live benchmark data (`run_20260913_144805`, `run_20260913_150517`, `run_20260913_151227`).

**4.12 Complete 7-Stage Driver Transition (RESOLVED — 2026-09-13)**

**Mechanism:**
- Abolished reliance on arbitrary numeric phase IDs (0–31); phase identity uses
  semantic filters.
- Replaced CLI execution with semantic filters: `--family` (SS, HH, HH_HPA, HS_HPA, DD, ZZ, CC), `--pattern` (Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk), `--shape`, `--stage`, and `--auto`.
- `phases.yaml` fully populated with 28 native families across 4 contraction patterns (228 clean targets; the live manifest = **418 phases** as of 2026-09-27, see `results.md` §1).
- Added `--dry-run` to inspect matched candidate targets before hardware execution.

**4.13 Parallel Clang Build, Cooldown Key Handling & Early Quit Reports (RESOLVED — 2026-09-13)**

**Mechanism:**
- Multi-threaded assembly compilation enabled by setting `CpuThreads: min(os.cpu_count(), 16)` in generated YAMLs and `make -j`.
- Fixed Tensile `ForkParameters` emission from `MacroTile0`/`MacroTile1` to valid schema `MacroTile: [[M0, M1, DepthU]]` fixing CC/DD configuration parsing.
- Integrated non-blocking `select.select()` listener in `_apply_cooldown()` so `'s'` skips cooldown sleep and `'q'` quits immediately.
- Ensured `acceptance_report.json` and `acceptance_report.html` are generated and persisted to `gfx90c_results/` even on early termination via `'q'` or interruption.

## 2026-10-12 — Docs whittling: `oto/harness/README.md` history archived

`oto/harness/README.md` was moved to `docs/developer/harness_runbook.md` (it is now inside the
documented ecosystem directory). Its `/tmp`-prototyping history and stale counts were
archived here.

# Archived from oto/harness/README.md (moved 2026-10-12)

## Historical note from L1–8 /tmp context (trimmed for changelog)

This content was preserved from the former harness runbook that referenced `/tmp` prototyping history. The original runbook has been relocated to `docs/developer/harness_runbook.md`; CPU-only/benchmarking contract and the ecosystem map are referenced there and in `claude.md`.

- CPU-only, never benchmarks: see `claude.md` §5 (Non-negotiable project guardrails) for the operational constraint.
- Ecosystem: see `docs/README.md` for the MD-docs-vs-docstrings boundary; layout and ownership now point at `oto/README.md` and `docs/developer/harness_runbook.md`.

## 2026-10-12 — docs restoration after the whittling (and one gate-harness fix)

The whittling pass (`7ef4213`) cut load-bearing detail from the human- and
agent-facing docs and replaced it with pointers. This restores it, merging the
pre-whittling content with the refactored structure:

- `README.md` — rebuilt as a self-contained high-level repo overview: a repo
  layout tree, full root-entry-point + per-package module tables, the complete
  validation-tool command set, the `.env` table, and the docs index (no longer a
  pointer chain). All internal links verified to resolve.
- `gfx90c_tuning_guide.md`, `kernel_tuning_research.md`,
  `gfx90c_theoretical_limits.md`, `complex_gemm_research_brief.md`,
  `potential_configs.md`, `knowledge_base.md` — restored to their pre-whittling
  substance as self-contained starter documents for the tuning agent (knob
  mechanics + forwarding surface, measured regime tables, the three byte tables,
  complex-MAC accounting, the occupancy model, mutation strategies, and open
  research directions). Only provably-wrong facts were corrected (e.g. the
  `ZZ` byte width is `16`, not `8`; the occupancy rule is `accVGPR = TT0·TT1·weight`).
- Cross-references re-pointed to the current section numbering — the
  pre-2026-10-10 `potential_configs.md` `§13.x` / `§14.x` / `§8.6` citations no
  longer resolved.
- `oto/harness/occupancy_bounds.py` now imports `VGPR_PER_CU` from
  `oto/tensile/gates/vgpr_model.py` instead of re-declaring it (Refactor-1
  acceptance criterion 6: no device-constant scatter).

## 2026-10-12 — off-grid probe tier removed (candidate pool is now strictly in-grid)

The generator's only contract-violating arm was the **off-grid probe tier**
(`PROBE_CELLS`: SS 32/64/128, DD 128, forced DepthU 4, `graded: false`): those
rows addressed (shape, dtype) cells the shipped gfx900 library does not carry,
so they could never ship under the no-contraction / no-extension contract
(`tests/test_library_parity.py`). Per the "no candidates that don't adhere to
the contract at all" decision, the tier is deleted outright:

- `oto/harness/candidate_rows.py` — `PROBE_CELLS` removed.
- `oto/harness/candidate_pool.py` — the probe loop, the second (`probe_pool`)
  sink, the `graded` flag and the `sink`/`graded` params on `_offer` are gone;
  every emitted row is in-grid.
- `oto/harness/candidate_overlay.py` — `_write_overlay` no longer takes probe
  rows or `--with-probes`; the timestamped mirror carries only `phases`.
- `oto/harness/generate_candidates.py` — `--with-probes` and the `PROBE_CELLS`
  re-export removed.
- Tests rewritten (`tests/test_generate_candidates.py`): the probe-specific
  cases are replaced by a hard invariant — every generated row addresses a
  shipped-grid cell — and `_write_overlay` counts only newly-scheduled rows.
- Docs: the `PROBE_CELLS` entry (tuning guide), the A6 off-grid row and the
  §10.3 "mirror only" note (`potential_configs.md`) now state the exclusion.

The legacy in-grid `probe_N1..N5` seed rows and `probe_*` run-dir globs are
unaffected (they are inside the grid).

## 2026-10-12 — seed-pool cap removed (`--max-fp` default = no cap); duplicate CLI deleted

`--max-fp` defaulted to a hand-picked `300` with no derivation, and the same
`main()` (argparse + body) existed in **two** modules — `generate_candidates.py`
*and* `candidate_overlay.py`. The cap silently dropped 58 of the 358 rows the
builders emit (`_round_robin_prune`). It never limited the `--auto` convergence
loop (that is `--budget` iterations / `--mutation-budget` knobs); it only capped
the pre-built seed pool.

- `--max-fp` now defaults to **no cap**: `_round_robin_prune` takes
  `Optional[int]` and returns the pool unchanged when the cap is `None`. The
  whole emitted in-grid pool is seeded; `--max-fp N` remains as an explicit
  opt-in throttle.
- The duplicate CLI is gone: `candidate_overlay.py` keeps only the overlay I/O
  (`_write_overlay` / `_prune_candidates_from_seed` / `_round_robin_prune` /
  `_summarise`); `generate_candidates.py` is the single CLI.
- Also dropped the now-impossible `"probe"` priority key in `_round_robin_prune`
  and the pre-split leftover imports in `candidate_overlay.py`.
- Tests: added a no-cap no-op case. Focused suite
  (`test_generate_candidates.py` + `test_library_parity.py`): 38 passed.
- The dry run now reports the full pool (would append the rows the old cap had
  been dropping); `--max-fp 300` reproduces the old behaviour exactly.

- **2026-10-23 — the acceptance report refactor: two hidden submenus removed,
  redundant layers collapsed, visual/layout checks added.** The Family matrix
  replaced its per-size caret/nested-table with an always-visible hierarchical
  table (`<tbody class="family-group">` per family, `<tr class="size-row">`
  indented underneath) — 42 size rows are now scannable without a control. The
  Problem-space coverage collapsed three parallel representations (summary
  table + 7 family `<details>` + 38 figure captions) into one grouped table
  (`<tbody class="coverage-group">` with `<tr class="group-row">` subtotals
  and `<tr class="coverage-row">` cells) and one appendix
  (`<details class="figure-appendix">` with `<h3 class="figure-family-title">`
  per family). Removed: `JS_ROW_EXPAND` script, `.row-toggle` button,
  `.family-detail` / `.size-table` / `.figure-group` CSS, the broken
  `\x15B8` caret escape, and the duplicate `Best measured` column from the
  coverage table (performance belongs in the Family matrix). Added:
  `oto.harness.visual_check` (playwright-based desktop/mobile viewport test),
  `tests/test_visual_check.py`, and a section-note explaining each table's
  structure. Preflight: `generate_candidates --dry-run` 1089, `check_candidates
  --quiet` 0 illegal, full suite 922 passed / 8 skipped.

- **2026-11-13 — the docs ecosystem gets two agent classes and a registry test.** All owner docs are now class-tagged (`dev` / `operator` / `shared`) in the `docs/README.md` registry: class A (developer agents working on oto) routes to `claude.md`; class B (operator agents producing a best-effort library for an unsupported AMD platform) routes to the new `docs/operator/operator_runbook.md` — preconditions → detect → starter pair → agent research → human verification gate → docs synthesis (the `<codename>_*.md` artefacts) → CPU-only harness study → TTY benchmark → `--best-library` → verification matrix and failure table. `claude.md` §1 and `README.md` §7 carry the same routing. `tests/test_docs_registry.py` now fails when a tracked Markdown file is unregistered, when a registry glob matches no tracked file, or when a registry row lacks a class tag. Registered this round: `archive/*.md`, `plans/test_optimization.md`, `oto/README.md`, and the starter-pair docs. Removed stale `plans/verify_*.py` registry row (no such tracked files). Also landed the harness toolkit for class A/B use (`oto/agents/harness_tools.py`: corpus census with floor/native split + TARGET_CELLS coverage, round-robin candidate proposals, CPU-gate verification, `build_harness_study`) wired into `--generate-device-docs`, which now also writes `<codename>_harness_study.md` and `<codename>_potential_configs.md`.

- **2026-11-13 — the CLI front door (`oto`) lands (Phase 1–4 of the CLI UX rework).**
  Replaced the multi-mechanism root shim with a single verb-first front: subcommands
  (`tune`, `run`, `bench`, `status`, `report`, `doctor`, `preflight`, `candidate`,
  `retirement`, `analytics`, `synthesis`, `verify`, `check`, `library`, `agent`,
  `consolidate`, `stats`, `chart`, `version`, `help`, `completion`), global flags
  (`--base`, `-q/--quiet`, `-v/--verbose`, `--no-input`, `--no-color`, `-n/--dry-run`,
  `-y/--yes`, `--live {on,off}`, read-only `--json`). Root `oto.py` deleted; `bin/oto`
  over `python3 -m oto` is the repo-local entry. `oto doctor` (toolchain/GPU/registry/
  corpus/docs), `oto check db|retirement`, `oto verify all --json`, `oto chart`,
  `oto candidate --json`, generated `docs/cli.md` (single source of truth) all wired.
  Full suite green: 1044 passed / 8 skipped / 242 subtests; ruff + py_compile + pyflakes
  + function/file-length + interactive-keys gates clean; no new failures vs the pre-existing
  `verify_all` baseline.

- **2026-11-14 — explicit DeviceProfile threading, end to end (the C2.5–C2.9 close, for real).**
  Every profile-consuming function in the package now takes an explicit
  `profile=None` kwarg resolved through the new `oto.device.loader.resolve_profile`
  choke point (explicit always wins; `None` = ambient `current_profile()`).
  Internal call sites thread the caller's profile instead of silently
  re-resolving ambient; import-time frozen captures (`FAMILY_TO_DTYPE`,
  `_DEFAULT_CELLS`, `SHIPPED_CELLS`) are now lazy derivations or `__getattr__`
  shims. Implementation was AST-verified at every step: Stage 1 added the kwargs
  (144 functions), Stage 2b threaded call sites with *qualified* resolution
  (from-imports, package re-exports, `self.` methods — never bare attribute-name
  matching, which had corrupted `dict.get`-style calls), and an AST fixer
  collapsed duplicated positional+keyword `profile` passes. Stage-2's failure
  modes were caught by the parse gate and the suite (`dict.get` TypeError), and
  rolled back cleanly before being re-done qualified. Gates now route through
  `resolve_profile` uniformly; `_store_knobs_feasible`'s docstring-swallowing
  bug (profile resolved *before* the docstring) fixed en route. New
  `tests/test_explicit_profile_threading.py` proves the explicit path: gfx90c
  refuses complex GSU>1 (no MFMA), a fabricated MFMA-capable *synthetic test
  profile* (codename `synthetictest`, has_mfma=True — never gfx90c, never a
  shipped profile) passes it, and `validate_config` threads the explicit
  profile into every gate it calls.
  The verifier's ast-equivalence check now recognises the Refactor 2 signature
  shape evergreen (a signature delta of exactly one trailing defaulted
  `profile=None` is the expected shape, base-agnostic; anything else still
  fails loudly) — `oto verify all` at HEAD: ALL EQUIVALENCE CHECKS PASSED.
  Suite green at every commit step: 1061 passed, 8 skipped, 242 subtests.
  Commits `e5ebdc4` (choke point + gate retrofit), `ae99b75` (the sweep, 81
  files), `0807157` (threading test), `a7500ea` (verifier). Follow-through:
  every function whose signature carries the `profile` kwarg (178) documents
  it in its docstring — the documented functions gained the kwarg line, the
  docstringless functions gained a one-line docstring, single-line docstrings
  were expanded in place, and the required-`profile` agent entry points are
  documented as required, not "optional ambient" (an injected claim caught
  and corrected).

- **2026-11-14 (27th) — the operator campaign playbook lands (`docs/operator_campaign.md`).**
  The convergence prompt that produced the gfx90c work is formalised as the
  standing, persistent procedure for Class B operators running a multi-session
  tuning campaign after the best-effort library exists. Content: the two hard
  display-session rules (GPU only in the user's TTY; CPU gates are not
  measurement); the persistent operating model (state lives in the ledger /
  kernel_db / acceptance report / deck overlay, never in context); the
  session-start checklist (`oto doctor`, `oto verify all`, `kernel_db --rebuild`,
  `resolve_cells --taxonomy`); Phase 1 corpus study with the exact tools and the
  like-for-like/clock-coverage/typecode attribution rules; Phase 2 straggler
  decomposition (W walls, R residency, C complex accounting, K clock confounds,
  D depressed-cell/sweep-order, F floor-steal-with-documented-tweak, N virgin
  axes — detect / route / closing evidence each); Phase 3 candidate routes in
  priority order (machine-driven narrow/wide via `oto tune` + the DB mutator,
  targeted DECISION_TRIAL_TILES rows, documented floor steals, virgin axes);
  Phase 4 consultation triggers (T1 verdict flip, T2 three batches without a
  band move, T3 CPU-unexplainable anomaly, T4 hardware-fact consequence,
  T5 campaign complete) with a self-contained payload protocol — never spend a
  consultation on a question a CPU tool answers; Phase 5 the per-batch
  autonomous loop (rebuild → report → census → triage → deck → next batch);
  Phase 6 the 10+ h overnight run. Registered in `docs/README.md` (Class B);
  `operator_runbook.md` and `skills/class_b_operator.md` now route the campaign
  there; `docs_index.json` regenerated; registry + index tests green.

- **2026-11-14 (28th) — CC:256/512 AF0EM=4/AF1EM=4 ADOPTED (owner decision, Option B).**
  The two Tensile-recipe rows (`_af4em4`: `mt64x64x8 / tt4x4 / VW2 / GLVW2/2 /
  WGM4 / AssertFree0ElementMultiple=4 / AssertFree1ElementMultiple=4`) ship in
  `phases.yaml` as first-class CC rows (deck 279 → 280; CC 47 → 48); the D5
  pilot row graduated and left `DECISION_TRIAL_TILES` (only D1 remains, with
  D2/D3 already retired 2026-11-14). `oto check candidates`: 280 checked,
  0 illegal. GPU legality carried over: both rows are the same config already
  validated with `NumElementsToValidate=128` on silicon at both shapes. fp for
  the 256 row is unchanged (`ca20ec…`); the 512 row is new (`75c7e5ce…`).
  What adoption does NOT claim: faster. The AF4/4 rows are reference-deck now;
  the A/B against AF2/2 (paired-widen) and AF1 (base) is the overnight runs'
  job; bars do not move without TTY measurement. Rationale: the vendor recipe
  (sgemm_large_square_nt.yaml, AF0/1EM=4) is the default the vendor ships
  for f32 free dims; 6 gates passed, GPU-validated, zero new machinery; A was
  the "unproven unless measured" option, B the "adopt proven-legal, measure in
  the campaign" option; owner chose B. Commit: phases.yaml rows, decks.py
  DECISION_TRIAL_TILES (D5 removed with the adoption record),
  tests/test_knob_sweep.py docstring + assert, knob_sweep CLI help string.

- **2026-11-14 (29th) — operator_campaign.md rewritten after deep history study.**
  Full re-derivation from primary sources: backrocm git history (FOSS United
  grant, Jul 2026; attempt1 ~9.2K LoC shell suite, ruler math broken four ways,
  retirement conflation, telemetry gaps), attempt2 (the draft run and the
  append-only import decision), the ROCm reference corpus (ROCm/AMD
  vis-à-vis GPUs research diaries, CDNA/Vega first-party papers) and the full
  oto commit graph (2026-09-17 → 2026-11-14). The doc now carries the
  genealogy explicitly, the neurosymbolic division of labour (neural proposals
  enter only via the symbolic gates + Tensile reference validator), the
  persistent session protocol (state on disk — kernel_db / acceptance report /
  resolve_cells / registry — read before any work), the exact corpus-study
  commands, the straggler class catalogue (W/R/C/K/D/F/N/H with detection and
  closing evidence), candidate routes in priority order (machine loop,
  targeted trial rows, documented floor steal, virgin axes, profile-rung
  Class A), and the consultation triggers T1-T5 with a self-contained payload
  contract. No fact in the doc is remembered; every date and claim was
  checked against the tree.

- **2026-11-14 (30th) — operator_campaign.md rewritten with full provenance.**
  Every constraint in the doc now carries its origin: the FOSS United grant
  (Jul 2026, method not product), attempt1 (~9.2K LoC shell; ruler math broken
  four ways; retirement conflation), attempt2 (draft acceptance gate rejected,
  floor itself retained), the oto birth (2026-09-17), Refactor 1 (package
  split), the 2026-10 failures that made this curriculum (ComplexFloat/complexDouble
  Z=8 gate miss, StaggerU inverted, LocalSplitU shadowed by explicit WorkGroup,
  TransposeLDS unreachable, sweep-order depressed CC:256, complex bar 4x scale,
  arm-size order-statistics artifact), rocm-libraries/nightly port, Refactor 2
  (device profiles, NumElementsToValidate=128, explicit profile threading) and
  the CC AF4/4 Option-B adoption. The doc now spells the bounded operating
  model: corpus study with concrete commands, the class catalogue with
  detection and closing evidence (W/R/C/K/D/F/N/H), candidate routes in
  priority order (machine loop; targeted DECISION_TRIAL_TILES; documented floor
  steal — worst cells only, every knob documented, no byte copies,
  gate + oracle + TTY or it did not happen), consultation triggers T1-T5 with a
  self-contained payload contract, and the post-batch autonomous refinement
  loop. No fact remembered; every claim checked against the tree or the two
  reference checkouts (backrocm, ROCm/).

- **2026-11-14 (31st) — the test suite is hardware-adaptive.** The triage of
  `test_explicit_profile_threading.py` flagging a misread of a fabricated
  `has_mfma=True` probe (`synthetictest`) surfaced three real defects, all
  fixed: (1) the probe fixture is renamed `probe_test` with a module-level
  note spelling out that it is a synthetic ISA (9,9,99) fragment, not a
  description of any target silicon; (2) the three ambient-codename tests now
  assert the loader's invariant (`DEFAULT_CODENAME == "gfx90c"`, explicit
  always wins, bounded rebinds restore the prior ambient) instead of assuming
  the ambient *is* gfx90c — a gfx902 box no longer trips these; (3) every test
  that reads the live, gitignored campaign outputs (kernel_db.json,
  phases.seed.overlay.yaml, acceptance_report.json, reference_rerun_manifest)
  now skips cleanly when those artifacts are absent — a fresh gfx902 checkout
  stays green minus the gfx90c-acceptance anchors, and the deliberate ones
  (load_profile("gfx90c") anchors + best-library carve tests, which require
  the corpus) skip with a reason instead of failing, so a gfx902 checkout
  fails loudly nowhere; every skip reason says "run the tuning campaign
  first". ruff clean; suite runs unchanged against this machine's corpus.

- **2026-11-14 (32nd) — tracked tree stops referencing machine-local scratch.**
  `oto/tools/verifiers/ verify_ast_equivalence.py`, `verify_gate_differential.py`,
  `verify_report_html.py` and `_verdicts_worker.py` wrote candidate-side byte
  artefacts into a hardcoded `/tmp/opencode/`; the evergreen verifier now
  materialises scratch under `tempfile.mkdtemp(prefix="oto_evergreen_scratch_")`
  via a new `oto.tools.verifiers._evergreen.scratch_dir()` (process-lifetime,
  atexit-cleaned), and the worker that executes inside a *ref worktree* builds
  its own `tempfile.mkdtemp` (it must stay oto-free).
  `oto/tensile/best_library.py` no longer silently prepends a system clang
  (`/usr/lib64/rocm/llvm/bin`) to `PATH` when the user did not set
  `ROCM_LLVM_BIN` — the LLVM bindir is derived from the user's own
  `ROCM_PATH` (wheel layout `lib/llvm/bin`, tarball layout `llvm/bin`).
  `logs/oto-error.log` (a tracked live log containing this machine's absolute
  paths) is untracked; `logs/` is now gitignored — never commit logs.
  Verifiers: ALL EQUIVALENCE CHECKS PASSED; ruff clean; suite 1061 passed.

- **2026-11-14 (33rd) — tests fully path-portable; tracked tree scrubbed of
  machine-local paths.** Every test that referenced the historical
  `gfx90c_runs/` / `gfx90c_results/` names now resolves them from the profile
  via `oto.runners.paths` (`runs_rel`/`results_rel`), so the suite runs
  unchanged on any codename with a matching profile. No tracked test or
  source file references `/tmp/` or any machine path; the evergreen verifier's
  candidate-side artefacts now materialise under
  `tempfile.mkdtemp(prefix="oto_evergreen_scratch_")` owned by
  `oto.tools.verifiers._evergreen` (atexit-cleaned), the gate-differential
  worker (which executes inside a REF worktree) builds its own scratch
  inline. `logs/oto-error.log` untracked. Suite 1062 passed, 8 skipped;
  `oto verify all` ALL EQUIVALENCE CHECKS PASSED; ruff clean.

- **2026-11-14 (34th) — deterministic limits derivation; operator campaign doc is self-contained.**
  New `oto/device/derive.py`: ALU peaks derived from profile hardware facts
  by one formula (lanes = num_cus x simds_per_cu x lanes_per_simd; FP32 =
  2 x lanes x fGHz; FP16 fast_F16 = 2 x FP32; FP64 = FP32 / 16; complex
  families inherit their lane class), with `python3 -m oto.device.derive`
  printing them on demand — agent-1's `_peak_table` emits derivation-by-loop
  matches from `oto.device.derive` so the limits doc can never drift from the
  formula. `tests/test_derive.py` locks it in (10 tests, exact-int equality
  against both `peak_gflops` and `theoretical_peaks_blas8`). Docs ecosystem:
  `docs/operator_campaign.md` rewritten fully self-contained — no
  requirements on reading git history; the doc spells the two development
  models (informed = a spoof reference exists, floor-steal protocol;
  blind = unsupported silicon, derive everything from scratch and propose
  the matrix from gh facts); the operator is a first-class runner, not a
  human-supervised process; GPU legs remain TTY-only; walls stay walls.
  gfx90c_theoretical_limits §2 now points directly at the derivation so the
  doc can never silently disagree with the formula.

- **2026-11-14 (35th) — operator_campaign.md is now self-contained; the operator agent holds the GPU.**
  The first re-draft was wrong on three counts, all fixed in this entry: (1) it
  shipped no content copyable from the project's own history without pointing
  the agent at git logs it does not have; (2) it stripped the GPU from the
  operator agent as if the operator were a GUI-session worker — the operator is
  the TTY runner and benchmarks are its job; (3) the 38-cell matrix is now
  carried verbatim in the doc so the agent never needs a second file to know
  the target list. The doc is now: preflight → starter file → `oto doctor` →
  `oto agent generate` → `oto library best-effort` → `oto tune` →
  `oto report --json`, with §5 branching into two development models
  (informed convergence with a spoof floor; blind convergence with derived roofs
  and no floor at all) and §11 decomposing every tie/loss into its class
  catalogue with an exit condition. The runbook breaks TTY/bench semantics only
  for the GPU-loss guard: the loop aborts rather than burn a night on a dead
  GPU. Initial framing fixed the agent class boundary instead of conflating
  it with display-session workers.

- **2026-11-14 (36th) — the toolchain contract is closed: explicit env, never a silent skip.**
  `oto/runners/toolchain.py`: the resolver accepted a ROCM_LLVM_BIN/ROCM_BIN/
  TENSILE_ASSEMBLER set to a nonexistent path and silently fell back to the
  derived layout — a user who typo'd their path got a working site built
  against the system tree instead of the one they asked for, with zero
  signal. Every explicit value now raises with the bad path spelled out;
  the derived layout is probed in order and reported; HIP_DEVICE_LIB_PATH is
  derived from the user's ROCM_PATH (lib/llvm/amdgcn/bitcode or the old RPM
  layout), never defaults to a system tree. `oto doctor` prints the full
  resolved dashboard: every path variable with existence, plus the exact
  assembler version line and the Tensile bin/Tensile version line; a broken
  .env reports the broken key with its bad value, no fallback. `.env`
  pins HIP_PATH=ROCM_PATH (explicit, removes ambiguity) and ROCM_VERSION
  for the nightly build; `.env.example` now states the contract in line 1:
  nothing falls back to /usr, /usr/lib64, or /opt/rocm unless you write it
  there yourself.

- **2026-11-14 (37th) — operator_campaign.md gains §9A: the candidate-generation strategies in one place.**
  The operator reference the three generation strategies scattered implicitly
  through §9 (`oto tune`) and §11 (the straggler-class catalogue) and never named
  the fourth — EXPLORE — nor why they were ever proven to win. New §9A names all
  five (NARROW / WIDE / DIRECTION / EXPLORE / STEAL), cites concrete corpus
  wins for each (the DD:192/256/512 +267 %/+20 %/+7 %; the CC:256 pad blind
  spot every GCN5 perf yaml shares; the CC/ZZ firm caps at 16384/8192 elements;
  the R8 CC:256 steal as the only "take the floor verbatim" example the corpus
  has ever validated). Hierarchy documented: NARROW first on the cheapest
  gradient, WIDE for geometry hops, DIRECTION informed-mode fastest path,
  EXPLORE for census-marked virgin axes, STEAL only with a documented
  floor-steal protocol (§12) and never for winning cells. Reading order for any
  cell: census → taxonomy → gate candidates. No other sections changed.

- **2026-11-14 (38th) — operator_campaign.md gains §11A: the corpus's own lessons, distilled.**
  After a full walk of the potential_configs.md diff history (26 commits that
  touch the file: verdict-flip re-annots, like-for-like regrades, the 2026-10-15
  ordering fix that reversed "THE ONE LOSER" CC:256 (it was a deck-order
  defect, not a kernel deficit), 18 re-analyses of the straggler list, the
  2026-10-10 complex-accounting correction (Tensile's client charges 2 flops
  per MAC — complex GEMM is reported at 1/4 its BLAS-8 GFLOPS), the floor-steal
  record (the one steal the corpus endorses, §R25: `MacroTile 64x64 / WorkGroup
  16x16x1 / GLVW 2/2 verbatim, everything else re-swept; verbatim copies count
  as nothing), and the 2026-10-21 R47 re-derivation that shrank the ORANGE
  list from 12 to 3 by streaming every claim through the corpus census), nine
  lessons are now stated in the operator doc, each tied to its source evidence
  as a rule of thumb: identical-config deltas are environment noise (±17.5%,
  never chased), like-for-like is the only graded basis, complex GEMM reads at
  80-97% of the roof, Tensile's refusal is the silicon not the bug, sweep
  order is causal (the 2026-10-15 lesson), structural locality beats byte
  copying, informed-mode steals are documented-retunes not verbatim copies,
  dead axes and silent placebos were a real failure class, gates are silicon
  facts not suggestions. One heading previously swallowed by an edit was
  restored; docs_index regenerated; docs tests green.

- **2026-11-14 (39th) — the corpus lessons are now device-general (§11A).**
  The nine lessons §11A shipped in the prior commit were gfx90c-shaped: L1
  tied the noise band to this device's clock telemetry; L2 quoted this-device's
  412-vs-98 GFLOPS family/single read; L3 was the complex-GEMM correction; L4
  named gfx9-specific gate outputs; L5 named this repo's shape-order fix; L6
  named gfx900 floor geometry; L7 named this repo's 2026-10-16 steal record;
  L8 named this repo's emitter-forwarding bug; L9 named this repo's gate
  calibration contract. All nine are rewritten to stand on any GPU this
  project supports (and any other GCN5-class APU the operator lands on);
  illustrative numbers retained with explicit "device this methodology was
  built on" framing. Device invariants explicitly stay in profiles/*.json
  where they belong.

- **2026-11-14 (40th) — operator_campaign.md locks the boundary: read-only by contract.**
  The original convergence prompt is now anchored to a self-contained class-B
  protocol with sharper territory lines than any prior pass: §0 now spells
  "You are not the developer" — no edits to `oto/`, any `.md`, profiles/,
  `phases.yaml`, `.env` or the registry (read-only via `mode=ro`); §15 is the
  absolute list of writable paths (campaign artifacts in `<codename>_results/`,
  report JSON, kernel_db via the `oto.harness.kernel_db` verb, overlay only via
  `oto.harness.generate_candidates`, bugs.md for any defect, never anything
  developer-owned); §13 gains rules binding the agent to §16 consultation
  doctrine (consult only when one of five lift gates fires; never freestyle chat;
  never consult mid-cut; answer-artifact-tagged stops); §16 is the full
  consultation schedule. §17 carries the 38-cell matrix verbatim. Two sloppy
  constructions from the earlier §13 rewrite fixed.

- **2026-11-14 (41st) — plans/ is gone; the tree is smaller by design.** The remaining
  one-shot plans (MASTER_PLAN, RENAME_AND_DOC_CLEANUP, CLI_UX_REWORK,
  REFACTOR_2_UNIVERSAL_GPU, AGENTIC_POTENTIAL_CONFIGS, test_optimization) are
  deleted — their durable content was folded into `incomplete_work.md`,
  `claude.md`, `docs/operator/operator_runbook.md` and this log before removal. The
  docs/root layout was flattened to a single `docs/` home:
  `mapping.md -> docs/shipped_floor_contract.md`,
  `results.md -> docs/gfx90c/results.md`, `knowledge_base.md -> docs/gfx90c/knowledge_base.md`,
  `gfx90c_theoretical_limits.md`, `gfx90c_tuning_guide.md`,
  `implementation_plan.md` (kept, not deleted: self-contained driver
  architecture + triaged fixes), `potential_configs.md -> docs/gfx90c/potential_configs.md`,
  `tensile_tuning_context.md -> docs/search_philosophy.md`,
  `kernel_tuning_research.md` + `complex_gemm_research_brief.md` -> `docs/research/`,
  `adversarial_review.md -> docs/developer/audit_register.md`;
  `implementation_plan.md` and all references re-pointed; `context.md` /
  `context_raw.md` were untracked owner scratch and are out of scope. `prior_*`
  moved to `archive/`. Module renames across `oto/` (34) and `tests/` (13):
  `metrics/{analytics->benchmark_analytics, coverage->cell_coverage,
  protocol->measurement_protocol, read_thermals->thermal_telemetry,
  report->acceptance_report, status_common->status_helpers}`,
  `runners/{auto->convergence_loop, clocks->clock_telemetry, paths->result_paths,
  phases->phase_runner, reporting->acceptance_reporting}`,
  `device/{derive->derive_limits, detect->device_detect, vocabulary->kernel_vocabulary}`,
  `ledger/{agent->convergence_agent, agent_mutate->agent_mutation}`,
  `harness/{generate_candidates->candidate_generator, measure_vgprs->vgpr_measurement,
  resolve_cells->cell_resolver}`,
  `tensile/{best_library->best_effort_library, decks->family_decks, patterns->contraction_patterns,
  shipped_library->shipped_floor, shipped_manifest->shipped_floor_manifest, synthesis/manifest->pipeline_manifest}`,
  `tools/{allruns->run_census, chart->benchmark_chart}`,
  `checks/retirement->stability_retirement`, `cli/docs->help_command`,
  `agents/{orchestrator->meta_agent, research->research_client}`,
  `oto/{yamlio->yaml_cached, inventory->readme_gen, docs_index->docs_index_writer}`.
  Verifier RENAMES rebuilt (old->new only, no identity keys). `gfx90c_vs_spoof.png`
  (generated artifact) removed. Suite green, verifier green, ruff clean.

- **2026-11-14 (42nd) — the CLI front is folded into the documentation ecosystem.**
  `docs/cli.md` is pinned to the live parser (`tests/test_docs_cli.py`);
  the migration table it carries maps the retired shims to the `oto <verb>`
  spellings; `oto <verb>` is now the only invocation shape the Class B
  operators see, and the Class A agents use the same. `PYTHONPATH=.`
  prefixes dropped from the operator campaign (every `python3 -m oto`
  invocation runs from the repo root, where the package is importable as-is);
  `docs/README.md` registry updated; README's file map displays current
  module names; the `oto` `--json` contract verified to emit JSON only on
  stdout with narration on stderr or /dev/null. `oto stats` and
  `oto check candidates --json` confirmed: one document on stdout, the
  per-line scan log on stderr. Suite green; verifier PASSED.

- **2026-11-14 (43rd) — `oto agent consult` lands; every one-shot plan in git history is now accounted for.**
  Plans resurrected from `git log --all -- plans/`: Refactor 1 (codebase org), Refactor 2
  (Universal GPU), CLI UX rework (front door, implemented), test optimization (9x suite speed-up),
  RENAME_AND_DOC_CLEANUP + INTUITIVE_NAMING (both executed earlier this arc), MASTER_PLAN
  (open items folded into incomplete_work.md), AGENTIC_POTENTIAL_CONFIGS (the one unexecuted
  plan). The last is now implemented as `oto agent consult [starter] [--with-docs]`: a CPU-only
  consult that emits `<codename>_potential_configs.md` — device identity from the profile,
  practical ceilings, a structurally-illegal rejection-taxa list, corpus priors from the local
  `kernel_db.json` (reference-device measurements, never claimed as this part's numbers),
  gate-checked ladder rows per family (refusals shown so they cannot sneak into a deck), and a
  TTY to-do list with zero measurements and no claims until the GPU runs. Synthetic-profile tests
  pass; no GPU required. Bug fixed en route: generate_device_docs crashed with FileNotFoundError
  when the `<codename>_docs/` directory did not exist. Suite green; verifier PASSED; ruff clean.

- **2026-11-14 (44th) — production-readiness audit: the plans archaeology is complete and the last unexecuted plan shipped.**
  Resurrected every one-shot plan from `git log --all -- plans/` and accounted for each:
  Refactor 1 (org), Refactor 2 (Universal GPU), CLI front door, test optimisation (9x faster suite),
  RENAME_AND_DOC_CLEANUP + INTUITIVE_NAMING (executed earlier), MASTER_PLAN (open items folded into
  incomplete_work.md), AGENTIC_POTENTIAL_CONFIGS — implemented as `oto agent consult [starter]`
  in 8b73424. Repo state at audit: suite green (1081 passed + 8 skipped), `oto verify all` PASSED at
  HEAD and 2824c2f, ruff clean, functions ≤ 60 lines / files ≤ 600 lines, docs registry fresh, no
  machine-local paths in tracked files, no .pyc/artifact files tracked, no stale module references
  outside changelog/archive, Class A/B docs current, `oto doctor` clean. The 44th entry closes the
  arc begun 2026-11-13 with the CLI front door and the 2026-11-14 doc restructure.

- **2026-11-15 (45th) — the production-readiness sweep: every audit finding fixed honestly, and the box declared honestly not ready.**
  The v1-readiness audit (A.md/B2.md) findings were fixed, in priority order, one concern per commit:
  - **Reference floor crash**: `_create_reference_run_dir` returned a 4-tuple bound into the sqlite `run_id`
    — every `--gfx900-reference` run died after the GPU work with a ProgrammingError. The caller now
    unpacks the tuple, the run row is stamped, and the pre-existing run dirs are restored in `finally`.
  - **`oto check db` honours integrity**: `--json` reports the real `PRAGMA integrity_check` and exits 1
    on corruption (it hardcoded `integrity: true` and exit 0); the human path exits 1 on failure too.
  - **The mutation arm cannot bypass the ledger guard silently**: `bypass_identical_skip` is honoured
    only when the ledger backs the bypass (agent present + outcome signal), never unconditionally.
  - **DB synthesis arm reachable again**: `convergence_agent` imported `db_mutator` from a nonexistent
    top-level module behind `except Exception: None`; it now imports the real module path and warns on stderr.
  - **`idx_cell_key`** is created by the schema (`_EXPRESSION_INDEX_DDL`), so a fresh DB has it.
  - **Native-subject selection is profile-aware**: `latest_run_id(arm="native")` excludes the *current
    profile's* spoof prefix (LIKE-escaped, parameter-bound), not only `gfx900_ref_%`; smoke floors are
    never recalled for promotion (`latest_reference_run_id` filters `meta.smoke`); the remaining
    `LIKE` interpolations across registry_queries / shipped_floor_manifest / run_plan / auto_prompt are
    parameter-bound (`like_escape`, shared). **Every** `startswith("gfx900_ref")` / `"gfx900_ref_locked_"`
    site across the harness/agents/metrics (kernel_db, occupancy_bounds, corpus_census, cell_knob_diff,
    cell_resolver, regression_matrix, gate_calibration, driver._current_arm, consolidate_floor.locked_run_id)
    now resolves the profile's spoof_reference through `oto.device.loader.spoof_prefix` — a gfx906-floor
    profile no longer misclassifies the floor as native anywhere in the pipeline.
  - **The driver honours OTO_PROFILE**: an explicit OTO_PROFILE binding wins over rocminfo detection
    (documented resolution order), so a gfx902 session is not silently run as gfx90c; the process-wide
    rebind failure prints to stderr instead of vanishing.
  - **Toolchain compilers**: the client-build compiler defaults follow the ROCm tree (llvm-bin amdclang
    preferred, matching Tensile's native default) with explicit `TENSILE_CXX_COMPILER`/`TENSILE_C_COMPILER`
    overrides (bare names pass through verbatim; bad paths are hard errors); `hipcc` is selected only
    when the tree ships no clang. `.env.example` documents both.
  - **`--prebuilt-client` is honest**: `OTO_TENSILE_CLIENT` pointing at a missing path is a hard error;
    the default is also verified — the campaign raises before any phase instead of failing inside every
    Tensile subprocess. `oto doctor` gained a "Tensile client" row that FAILs on this box today
    (the client is genuinely not built here; the fix is the one-time next-cmake build, not a code edit).
  - **`oto candidate --json` mirrors the text view**: `phases` is the deck (280), with `seed_overlay`
    (1146) and `manifest` (1426) as distinct fields instead of a merged-only count.
  - **CLI housekeeping forced by the 600-line file guard**: adapter helpers extracted to
    `oto/cli/_adapter.py`, the verify adapters to `oto/cli/verify_cmds.py`; `commands.py` keeps its
    stated public API (`dispatch`, `show_help`, `write_completions`).
  - **`oto verify all --base-ref REF`** passes a base ref through to the verifier (previously
    `--base` was swallowed by the global flag and the verifier silently ran HEAD~1).
  - **Comparator/verifier repairs**: split-era MOVES pointed at renamed paths (`oto/checks/db.py`,
    `oto/ledger/queries.py`, `oto/ledger/proposals.py`); `harness/occupancy_bounds.py` MOVES source
    corrected to `harness/occupancy_audit.py`; `verify_methods.py` NEW list follows renames; the
    config-writer accepted classes now cover exactly the documented emitter deltas
    (`+ Architecture:` echo, `NumElementsToValidate: 0 -> 128`) and their composition with the
    already-accepted knob classes); 21 manifest attestations added for the
    mechanical Refactor-2 evolution signatures; `oto verify all` returns 5/5 OK at both HEAD and 2824c2f.
  - **Slop retired**: accept-report generation failures raise loudly (calls cannot tell a dry run from
    a bug otherwise); the dead per-family `_<fam>_mutation_pattern` methods deleted; `self.scheduler`
    renamed `self.generator` throughout; the benchmark chart's device literals are profile-derived.
  - **Release-readiness additions**: pinned split requirements (`requirements.txt` runtime,
    `requirements-dev.txt` suite+lint), `NOTICE` (copyright assertion; LICENSE stays verbatim),
    `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS`. A GitHub Actions CI workflow was added
    in the same sweep, then **removed at the owner's direction (never requested -- the owner
    confirmed they did not ask for CI/CD)**. The repository has no CI; the suite is
    self-verified on the machine, and README quick-start + license section + regenerated
    `oto/README.md` landed in its place.
  Suite green (1084 passed, 8 skipped, 242 subtests, RC=0). `oto verify all` PASSED at HEAD~1 and at
  2824c2f. Ruff clean. Function/file-length guards pass. **The gfx902 bring-up is NOT unblocked**: the
  owner's API key and the Tensile client build are both still required.
- **2026-11-15 (46th) — the gfx90c record absorbed into the one gfx90c-specific doc, and potential_configs.md rewritten as the device-independent brief.**
  docs/gfx90c/potential_configs.md was historically the gfx90c working document (rewrites 1–8: the deck, the gates,
  the A/B audits, the like-for-like regrade, the steal, the stop-list, the overnight runbook). Its entire
  content — every measured number, table, run id, verdict and superseded rewrite — now lives in
  `docs/gfx90c/gfx90c_tuning_guide.md` §13 (all R-numbers preserved; bring-up case study for agents imitating a
  new-target port). The doc itself is rewritten as the device-independent methodology: what a deck is, the
  zero-calibration gate method (accumulator / register-file / LDS / load-divisibility / oracle), the
  like-for-like measurement rules (protocol parity, tie-band policy, rank-1 medians, sweep order), the
  literature-mapped experiment order, the ledger-trace reading, the overnight protocol, and the porting
  checklist. A full resolution table (`docs/gfx90c/potential_configs.md` §10) maps every former §-pointer so
  historical citations stay resolvable; non-R section references across docs, comments and tests were
  re-pointed mechanically to `docs/gfx90c/gfx90c_tuning_guide.md` §13. Registry (`docs/README.md`), generated index
  (`docs/docs_index.json`, via `oto agent index`), `docs/agent_reference.md`, `docs/README.md`,
  `README.md`, `claude.md`, `docs/gfx90c/gfx90c_theoretical_limits.md`, `docs/gfx90c/knowledge_base.md`,
  `docs/operator_campaign.md` and `docs/research/kernel_tuning.md` updated to the new split. No instrument,
  gate, verdict or deck row changed. The commit history of both files was studied first (65 commits on
  potential_configs.md; the 2026-10-12 whittle/restore cycle preserved). Suite RC=0.
  - **The agentic framing, applied everywhere (same concern).** Stale pre-agent-era claims that oto is
    "not LLM-in-the-loop" / "AI-free" / "one-shot deterministic convergence" were corrected: the agent
    layer is LLM-assisted and ships today (`oto agent consult`, agent-1/agent-2, directed prompts;
    proposes, never decides). `docs/implementation_plan.md` rewritten as the honest design brief
    (two loops, one rule; gfx902 blocked on the API key is stated, not hidden); the README architecture
    flowchart gains the agent layer and states the acceptance path is deterministic; `docs/search_philosophy.md`
    retitled (agentic tuning context; deterministic acceptance path; no surrogate in the loop; the model
    never decides); `claude.md` and `docs/developer/audit_register.md` updated likewise; `oto/__init__.py` docstring's
    opening line corrected; `oto/tools/potential_configs.py` citation updated.
- **2026-11-15 (47th) — the archive untracked, its history folded into the docs ecosystem, and the research-prompt discipline written into the operator workflow.**
  Per owner direction, `archive/` is no longer tracked in git (its content stays on disk, ignored via the
  standing `archive/` rule); nothing was deleted. The archive's markdown was studied first:
  - **The prior-campaign autopsy** (attempt1, 2026-09-04 → 09-13: the 9-file patch failure, the 3-entry
    shim port, the peak-table correction, the ±23–31 % A/B envelope, the GPU-hang playbook, the
    winner-instability autopsy) is absorbed verbatim into `docs/gfx90c/gfx90c_tuning_guide.md` §14; the research
    passes' audit trail is recorded as §15 (corpus.pass1–3, RESEARCH_PROMPT3, the pre-rewrite deck snapshot).
  - **The research-prompt discipline** — the multi-round, evidence-labelled, prohibition-guarded research
    workflow the campaign developed (one deliverable scoped exhaustively; three rounds: broad census →
    line-level coupling audit → docs triage; `VERIFIED`/`PARTIAL`/`UNVERIFIED`/`REASONING` labels; hard
    prohibitions; adoption matrices; pre-registered mechanism-tagged predictions; do-not-cite lists) — is
    written into `docs/operator_campaign.md` §18 as the procedure the operator agent follows when the docs
    cannot answer a question it must settle. Pinned in `docs/skills/class_b_operator.md` and
    `docs/operator/operator_runbook.md` §10.
  - **`.gitignore`**: `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`, `dist/`, `.mypy_cache/`, `.tox/` added.
  - The guide now carries the complete bring-up history: current method (§0–§12), the port case study (§13),
    the prior-campaign autopsy (§13.4), and the audit trail (§13.5). Suite RC=0.
- **2026-11-15 (48th) — results.md and the theoretical-limits doc split into gfx90c golden case studies and device-independent templates.**
  Same treatment as the potential_configs fold: `docs/gfx90c/results.md` was historically gfx90c-specific evidence. It is now
  `docs/gfx90c/gfx90c_results.md` (content unchanged, the gfx90c golden case study), and the new `docs/gfx90c/results.md` is a
  device-independent placeholder the agent populates per device — required sections (scoreboard with protocol+band,
  per-cell verdicts, gate census, straggler classes, clock/thermal discipline), the like-for-like admission rule,
  median-of-seeds, and the TTY-only rule. `docs/gfx90c/gfx90c_theoretical_limits.md` was already gfx90c-named; the new
  `docs/gfx90c/theoretical_limits.md` is its device-independent twin — ISA identity by probe, peak derivation from
  lanes×clock×throughput, the family table and the acceptance bar — referring to the gfx90c doc only as a golden
  worked example, never as a source of numbers. Cross-pointers added in both gfx90c files; all ecosystem
  references re-pointed (20 files); registry rows renamed + two template rows added; `docs/docs_index.json`
  regenerated; no numbers, instruments or verdicts changed. Suite RC=0; `oto verify all` PASSED.
- **2026-11-15 (49th) — owner-gated blocked items consolidated in `incomplete_work.md`.**
  C4/C7.1 (API key), Tensile client not built on this box, CC AF4/4 vs AF2/2 A/B (TTY-gated, no perf claim
  anywhere), and acceptance-report / drift-manifest attestation status — one consolidated section with
  pointers; nothing actioned, nothing claimed.
- **2026-11-15 (50th) — docs/gfx90c/knowledge_base.md split the same way: gfx90c golden case study + device-independent template.**
  `docs/gfx90c/knowledge_base.md` was historically gfx90c-specific (454→866 lines across 27 commits: born 2026-09-19; the
  Oct-2 overhaul accrual; the Oct-12 whittle/restore cycle that moved module-docstring facts into the code and
  deleted `knowledge_base_final.md`; the Oct-14 corpus3 fold (+184 lines: the @e8a8999e defaults table and the
  never-used-levers analysis, marked mechanism-verified/gain-unmeasured); the Oct-19 GCN5 literature folds). It is
  now `docs/gfx90c/gfx90c_knowledge_base.md` (content unchanged, in-file pointer added), and the new `docs/gfx90c/knowledge_base.md`
  is a device-independent template — required sections (What Is Tensile → Port mechanism → GlobalParameters →
  Solution space → Footprint → Kernel levers source-audited → Measurement science → Preservation law → Glossary),
  how the agent populates it (probe → pin evidence → derive, never inherit → 0 unlabeled claims), and the same
  hard rules as the results/limits templates: the gfx90c file is the golden example, never a source of numbers.
  22 files re-pointed; registry rows updated; docs/docs_index.json regenerated. Suite RC=0; `oto verify all` PASSED.
- **2026-11-15 (51st) — knowledge_base.md mined and generalised twin created; the gfx90c doc family of four is settled.**
  Full git history studied (27 commits; 454 → 858–866 lines): born 2026-09-19 (the port's WHAT-layer) → Oct-2 overhaul
  accrual → the Oct-12 whittle/restore cycle (module-docstring facts moved into code; `knowledge_base_final.md` deleted)
  → Oct-14 corpus3 fold (+184 lines: `@e8a8999e` defaults table + the never-used-levers analysis, marked
  mechanism-verified/gain-unmeasured) → Oct-18 gate formalisation → Oct-19 GCN5 literature folds → Nov mechanical sweeps.
  The file is now `docs/gfx90c/gfx90c_knowledge_base.md`; new device-independent `docs/gfx90c/knowledge_base.md` template (WHAT layer;
  populated per device by the agent). Mining: era note (toolchain moved to nightly 2026-11-14), §6 footprint table delegated
  to `docs/shipped_floor_contract.md` §2 (single source), §7 rate card delegated to `docs/gfx90c/gfx90c_theoretical_limits.md`
  §5 + `oto.device.derive_limits` (single source of peaks), §8.2 now points at the gate modules as normative.
  **Item 5 closed:** gfx90c-specific residue is absorbed or triaged — §6/§7/§8.2 delegated to their owners, §8.1/§8.3/§8.4/§7.1/§7.2
  are the KB's own canonical content (kept, pointed), and the four gfx90c-specific docs are split deliberately, NOT folded into
  the guide (documented in the guide §0a): bring-up case study + three golden examples. 22 files re-pointed; registry/index synced;
  suite RC=0; `oto verify all` PASSED.
- **2026-11-15 (52nd) — gfx902 pipeline readiness: ISA triple + Tensile client work (CPU-side).**
  `oto/device/tensile_isa.py` `ISA_TRIPLES` now carries `gfx902 -> (9, 0, 0x02)` (public LLVM ISA-version
  fact; not a measurement) so the CPU-only build proof can pin Tensile for gfx902 instead of refusing by
  default. Rehearsal tests updated (16/16 green); `docs/operator/starter_pair.md` BLOCKED list updated — remaining:
  profile + human verification + gfx902 silicon + the owner's API key, nothing else. The Tensile benchmark
  client is built for gfx90c from ROCm/rocm-libraries `next-cmake` against the extracted TheRock
  7.15.0a20260728 SDK (the venv HIP include shadows the nightly's hip headers; the full dist was used as
  CMAKE_PREFIX_PATH with its amd_smi). The client landed at `build/client/tensile-client` and `oto doctor`
  reports the row OK (21 ok, 0 FAIL); no `.env` change needed (doctor finds it at TENSILE_ROOT).
  Toolchain/client contract formalised as `docs/human/toolchain_client.md` + `scripts/build_tensile_client.sh`
  (CPU-only, fail-closed, parameterised by `--rocm-prefix`/`--targets`; tested in tests/test_build_tensile_client.py).
  The CPU-only `oto check tensile-build --arch gfx902` probe fails honestly inside Tensile itself —
  `KeyError: globalParameters["AsmCaps"][(9, 0, 2)]` at `SolutionStructs.py:3023`; the pinned checkout
  contains no gfx902 anywhere; the nightly clang assembles gfx902 v_fma_f64 and correctly refuses gfx902
  MFMA. What remains for the gfx902 bring-up is enumerated in `incomplete_work.md` (Open items):
  the owner's 3-entry Tensile patch (SupportedISA + architectureMap + AsmCaps, the gfx90c precedent),
  the human-verified `profiles/gfx902.json`, the API key, the TTY.
- **2026-11-15 (53rd) — v1 release prep: every actionable item finished; the audit checklist is closed.**
  - F-REPORT-4 closed: `_report_inputs` detects the degenerate like-for-like path (no analytics anywhere → the
    unfiltered per-run walk as loud fallback), marks it `protocol_fallback=True`, threads it through `_report_payload`
    into the `AcceptanceReport` model (`oto/metrics/report_models.py`) and writes `protocol_fallback` into
    `acceptance_report.json`. Locked by `tests/test_report_protocol_fallback.py` (2/2); attested in
    `drift_manifest.json` (ast_equivalence); `oto verify all` PASSED.
  - Audit checklist (`docs/developer/audit_register.md` §3) fully closed, every item with evidence:
    phases.yaml order is execution order — `tests/test_manifest_order.py`; the complete `should_run` gate
    matrix — `tests/test_policy_should_run.py` (scope hit/miss, tier-1, tier-2, tier-1 precedence,
    empty→RUN, identical-fp skip); single-writer SQLite + `json.dumps` verified line by line; telemetry
    header-in-file tolerated-and-reported; peaks only in the profile loader (`oto.device.peaks` gone);
    detached+killable GPU phases (setsid/kill/quit paths); `--phase-timeout` default 3600 s finite.
  - Synthesis blind-union exposure annotated honestly (admission gate = agent.harvest LCB; best-effort carve
    native→fallback→floor chain with provenance); no code change — the gate is deliberate and recorded.
  - `incomplete_work.md`: F-REPORT-4 removed (closed); every remaining item is an owner gate (API key, GPU TTY,
    human verification, owner word) — documented, marked owner-gated, never re-raised.
  - Docs registry unchanged: no new doc added; no doc deleted; every registry row still matches a tracked file.
- **2026-11-15 (53rd) — gfx902 pipeline readiness, CPU-side, complete.**
  `oto/device/tensile_isa.py`: `ISA_TRIPLES` carries `gfx902: (9, 0, 0x02)` (public LLVM ISA fact; not a
  measurement) so the CPU-only build proof pins Tensile for gfx902. The 3-entry Tensile-side patch landed
  in the rocm-libraries checkout (commit 386e90e): `SupportedISA` gains `(9, 0, 2)`,
  `architectureMap["gfx902"] = "vega10"`, `AsmCaps[(9, 0, 2)]` (derived via Tensile's own
  `GetAsmCaps()` against the TheRock nightly amdclang++ v23.0.0git — derived-vs-cached byte-identical to
  gfx90c's entry). `oto check tensile-build --arch gfx902` passes end-to-end: CC
  (MT=64x32x16/TT=4x2) and ZZ (MT=32x32x16/TT=2x2, `sols=1 vgpr<=71`). LLVM assembles gfx902
  `v_fma_f64` and refuses gfx902 MFMA (`instruction not supported on this GPU (gfx902)`). The Tensile
  benchmark client builds from `next-cmake` against the full TheRock 7.15 SDK (the venv's `include/hip`
  shadows the nightly headers; use the dist prefix) and is installed at
  `<TENSILE_ROOT>/build/client/tensile-client` — `oto doctor` reports the row OK (21 ok, 0 FAIL).
  `docs/human/toolchain_client.md` + `scripts/build_tensile_client.sh` formalise the contract
  (`--rocm-prefix`/`--targets`/`--tensile-root`/`--amd-smi-dir`; fail-closed; tested in
  `tests/test_build_tensile_client.py`, 7 tests). `incomplete_work.md` updated: the gfx902 Tensile-port
  step is closed (probe now passes) — what remains is `profiles/gfx902.json` (human verification),
  the owner's API key (C4), the gfx902 TTY. `docs/operator/starter_pair.md` BLOCKED list updated accordingly.
  Suite RC=0; `oto verify all` PASSED.
- **2026-11-15 (54th) — docstring-to-pdoc-prose pass + stale-docs purge + easy-mode UX.**
  Every function docstring in `oto/` rewritten to pdoc prose (135 `Args:`/`Returns:`/`Raises:` blocks eliminated;
  383 missing function docstrings added; private helpers get one line; Sphinx `:func:`/`:data:` roles converted to
  back-ticks; 22 mixin composition roots stated as dotted paths; `AbIdentityMixin` noted unused). Full suite green
  throughout (1123 passed / 8 skipped; the 600-line and 60-line guards kept via compaction; one dead `pass` dropped).
  Verifiers: the split-era check now PASSES at both `2824c2f` and `HEAD~1`; `verify_symbols.py` RENAMES table moved to
  `drift_manifest.json` (the line-budget ratchet had dropped two real mappings, `ldspad_gate.py`→`ldspad.py` /
  `occupancy_common.py`→`gate_common.py`, and false-reported whole-module API loss); restored mappings pinned by
  `tests/test_verifier_renames.py`. `oto check tensile-build` GPU legality probes on gfx90c (M=128): all eight PASS
  (CC af4em4/af22/base @256/512, ZZ DU8/DU16, trialD1) — `sols=1`, no matrix larger than 512³. `oto doctor` rc=0
  (21 ok, 2 pre-existing advisory WARNs). Easy-mode `oto setup`: all wizard narration moved to stderr (stdout stays a
  clean data channel), blank-default prompt artefact fixed, Ctrl-D path verified, UX contract pinned by
  `tests/test_easy_mode_ux.py`. Docs: README rewritten around the recovery-pipeline vision (blog/grant material);
  `docs/operator/operator_runbook.md` §19 blind convergence end-to-end (gfx902 worked instance, edge cases E1–E12, dead ends
  D1–D6); `docs/agentic_consult.md` folded into `docs/developer/invariants.md` §3.6–§3.8 and removed as a standalone file;
  registry deduplicated; `oto agent index` regenerated; `docs/overview.md` birds-eye fixed; Get Started/usage block
  satisfies the README↔cli.md freshness check. `phases.yaml`: CC:256 paired-widen AF22 control row added (fingerprint
  computed as the deck does) — 281 phases, 0 illegal.
