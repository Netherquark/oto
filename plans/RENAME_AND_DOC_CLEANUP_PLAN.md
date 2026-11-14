# RENAME AND DOC CLEANUP PLAN — v1 (proposed; no edits have been made)

**Status:** proposal only. Every rename, delete, merge, or split below is a
*recommendation* with a rationale and evidence pointer; nothing in this
document has been applied. Implementation is a later task with discrete
commits and a green preflight at each step.

**Scope:** every tracked file in the repo (297 files: 165 under `oto/`, 80
under `tests/`, 41 docs/config/root files), read for naming, for references to
ephemeral or deleted machinery, and for cross-doc duplication. Read-only
throughout; no file was edited to produce this document.

**Companion:** `plans/REFACTOR_2_UNIVERSAL_GPU.md` (the device-agnostic
re-organisation this plan sits on top of) and `docs/README.md` (the
documentation boundary contract and registry).

---

## 0. Method and safety rules

1. **No functional change.** Every item here is a name, a docstring, a
   comment, or a file-location change. No behavior, no API surface, no
   public class/function name changes (§1.4–§1.13 renames are all *module*
   renames with import rewrites).
2. **Mass-replace is mandatory, not optional.** Every rename must be a
   repository-wide `grep -rn "old_name"` + rewrite, followed by
   `python3 -m pytest tests/test_py_compile.py tests/test_pyflakes.py
   tests/test_ruff.py tests/test_function_length.py tests/test_file_length.py -q`.
3. **One rename class per commit.** Leaf modules (§1.4–§1.13) → runner CLI pair
   (§1.2/§1.3) → test family (§3) → `_rows_*` collapse (§2.3). Public API
   (`oto/__init__.py` re-exports) is untouched by (a)–(c).
4. **`oto/README.md` regenerates** from module docstrings via
   `python3 -m oto._map`; run it after any rename or the README lists ghosts.
5. **`docs/README.md` registry** must be updated in the same commit as any
   doc rename/move/delete; the registry test (`tests/test_docs_registry.py`)
   is the gate.
6. **`docs_index.json` regenerates** via `python3 -m oto agent index` after any
   docs change.
7. **No line numbers in the docs ecosystem** (claude.md §2.0 / docs/README.md
   boundary rule). This plan is allowed to cite them (it is a proposal, not
   part of the ecosystem); the resulting renames must carry their provenance
   into the code's `Owns:` block, not into the docs.
8. **`todo.txt` stays untouched** — it is the user's file, not ours (claude.md
   §2.0.1, §9.7). This plan does not reference it as an authority.

---

## 1. The problem statement (what a newcomer cannot find)

A developer landing on the repo for the first time faces three failures:

1. **Two CLIs share a package tree.** `oto/cli/` (the real `python3 -m oto`
   front) and `oto/runners/stage_cli.py` + `oto/runners/stage_flags.py` (the legacy
   stage-dispatch backend) differ only in an adjective that is not written
   anywhere. "flags.py" could mean either.
2. **"Phase" means three things.** A benchmark phase (`phases.yaml`,
   `oto/runners/phases.py`), a pipeline stage (`Stage 1..7` in
   `oto/runners/stage_cli.py:50-251`, `oto/cli/parser.py:131-205`), and a
   milestone code (`Option H Phase 1..4`, `Refactor 1/2`). Five test files
   carry the dead milestone vocabulary in their names.
3. **The private-helper convention is inconsistent.** Nine underscore-prefixed
   modules (`_rows_*`, `_status_common`, `_evergreen`, `_verdicts_worker`,
   `_map`, `_version`) coexist with public modules doing the same job
   (`gates/occupancy_common.py`, `gates/memo.py`, `tests/*_common/_fixture/
   _harness`). Privacy is expressed by name in some places and by `__all__` in
   others.

Section 3 of this plan fixes each failure with a concrete file-level action.
Section 5 fixes the ephemeral-reference violations.

---

## 2. The private-helper convention — one rule, one mechanism

### 2.1 What the tree actually does

Leading-underscore **module** names (privacy signal):
- `oto/harness/rows_ladders.py`, `rows_frontier.py`, `rows_smallcells.py`
  (imported by `oto/harness/candidate_rows.py:18-32`; their headers
  state the import order is "fixed and load-bearing" at
  `rows_frontier.py:5-6` and `rows_smallcells.py:5-7`);
- `oto/metrics/_status_common.py` (imported intra-package:
  `run_status.py:24`, `report_build.py:21`, `ledger_state.py:24`; its own
  header at line 10 says "module consumers only");
- `oto/tools/verifiers/_evergreen.py`, `_verdicts_worker.py` (imported
  intra-package: `verify_ast_equivalence.py:313,446`, `verify_method_
  equivalence.py:30`, `verify_gate_differential.py:75,98`);
- `oto/_map.py`, `oto/_version.py` (imported **cross-package**:
  `oto/_version.py` → `oto/__init__.py:34`, `oto/cli/flags.py:15`,
  `oto/cli/docs.py:16`, `oto/cli/commands.py:552,558`;
  `oto/_map.py` referenced as `python3 -m oto._map` in its own docstring
  line 15 and in `oto/README.md:3`).

Non-underscore shared modules doing the same job:
- `oto/tensile/gates/occupancy_common.py` and `oto/tensile/gates/memo.py`
  (same role as `_status_common.py`);
- `tests/occupancy_gate_common.py`, `tests/phase1_harness.py`,
  `tests/run_status_fixture.py` (test support, no underscore, not collected as
  tests — privacy expressed only by not matching `test_*`).

There is also no `__all__`-based privacy backup: `_status_common.py:10` says
its helpers are "module consumers only", yet `run_status.py:24` re-exports
them publicly. The underscore is the only signal and it is inconsistent.

### 2.2 Proposed consistent treatment

One rule, one mechanism:

1. **No leading underscore on module names anywhere in `oto/`.** Privacy is
   expressed by package boundaries + `__init__.py` docstrings + `__all__`,
   never by filenames.
2. Rename the offenders to plain names that state contents (§1.1, §1.6,
   §1.9, §1.13).
3. Keep the existing non-underscore shared modules as they are (after their
   own renames in §1).
4. If maintainers insist on keeping underscore modules, apply them
   *uniformly* (add the same treatment to `occupancy_common.py`) and forbid
   cross-package imports of underscore modules (CI grep:
   `oto\.[a-z_]+\.[a-z]*_[a-z]` outside intra-package). This is strictly
   worse; do not do it.
5. tests/: unify support modules under one suffix (§3.3) — three suffixes
   (`*_common`, `*_fixture`, `*_harness`) for one role.

### 2.3 The import-order fragility the `_rows_*` split encodes

`rows_frontier.py:5-6` and `rows_smallcells.py:5-7` state "Import only after
`rows_ladders` (they mutate `PLAN_BATCH`)"; `candidate_rows.py:8-9` calls the
order "fixed and load-bearing". That is a *module-design* smell (mutable
shared global across three files) unrelated to naming, recorded here because
any rename PR touching these three files should collapse them into
`candidate_rows.py` or a `rows/` subpackage with explicit ordered init — not
because of the underscores, but because "import order matters" is
incompatible with the rest of the package's explicit-composition style
(`registry.py`, `driver.py`).

---

## 3. `tests/` layout vs what it tests

### 3.1 The `phase1_*` family — dead vocabulary in live filenames

Five files carry "Phase 1" in their name and content:

- `tests/phase1_harness.py:2` — "Shared scaffolding for the Phase 1
  production-integration tests"; `:5` `_StubScheduler`; `:50`
  `tempfile.mkdtemp(prefix="oto_phase1_integration_")`; `:7` names
  `tests/test_phase1_*.py`.
- `tests/test_phase1_durability.py:2` — "atomic emission, WinnerFreq persistence
  and the negative cache"; imports `phase1_harness` (`:9`).
- `tests/test_phase1_overlay.py:2` — "overlay-merge and proposal run_id
  regression tests" (`:9`).
- `tests/test_phase1_readonly_gpu.py:2` — "read-only reporting and GPU-loss
  abort" (`:12`).
- `tests/test_phase1_writeback.py:2` — "skip/bypass, outcome write-back" (`:9`).

"Phase 1" here means **Option H Phase 1** — the proposals-ledger/mutator-
integration milestone from `docs/implementation_plan.md` (Hplan.3). It does **not**
mean a benchmark phase. And the workspace has since moved on: nothing in
`oto/` is named or framed as "Phase 1" except in comments
(`oto/ledger/proposals.py:29`, `registry_core.py:79,102`, `agent.py:61,79`,
`agent_mutate.py:80-83`, `ab_audit.py:282`, `driver.py:201`). To a newcomer,
`phase1_*` reads as "the first benchmark phase", colliding head-on with:

- `phases.yaml` (the committed candidate deck),
- `oto/runners/phases.py` (the phase runner),
- `oto/runners/benchmark.py` / `oto/cli/parser.py:181-205` ("Stage 1..7"),
- `oto/runners/driver.py:6` ("Phase-0 preflight", `:301-304`),
- `oto/runners/stage_cli.py:56` ("Stage 1: Phase-0 preflight" — same thing, two
  names in one file pair),
- `oto/cli/commands.py:26` (`_STRUCTURED_STAGE_JSON = frozenset({"candidate", "2"})` — a raw stage number beside a word),

and with the equally-live "Phase" milestones of the *other* project
("Option H Phase 2/3/4"), and the refactor milestones ("Refactor 1/2"). Four
naming systems, one word.

**Verdict: yes, the Phase-1 vocabulary is dead for newcomers.** Rename the
family to what the tests actually pin:

- `tests/phase1_harness.py` → `tests/support_convergence.py`
  (fixtures: one-row Cijk CSV, stub scheduler, `Harness` base for
  mutator+driver write-back tests; see §3.3's unified support-module
  convention);
- `tests/test_phase1_durability.py` → `tests/test_proposal_durability.py`;
- `tests/test_phase1_overlay.py` → `tests/test_overlay_merge.py`;
- `tests/test_phase1_readonly_gpu.py` → `tests/test_readonly_reporting.py`;
- `tests/test_phase1_writeback.py` → `tests/test_outcome_writeback.py`.

### 3.2 The rest of the "Option H phase" vocabulary in tests

(Per-file verdict + rename already enumerated in §1.14; full 80-file inventory
is in §3.6 of the agent's working notes — omitted here for brevity, but every
file was read and every rename is one-line-justified.)

Rule proposed: **file names never carry project-milestone codes; docstrings
carry them only with a one-line gloss of what the milestone was.** Everything
above can be fixed with a docstring sweep except the four `phase1_*` +
`*_phase3` cases, which need the file renames.

### 3.3 `tests/run_status_fixture.py` and `tests/occupancy_gate_common.py` — same genre, different suffixes

- `tests/run_status_fixture.py:1` — "Shared scaffolding for the run_status
  regression tests." Clear job; suffix `_fixture`.
- `tests/occupancy_gate_common.py:1` — "Shared helpers for the occupancy-gate
  regression tests." Clear job; suffix `_common`; `:4-5` "the gfx90c
  ground-truth table" (fine as data provenance); `:18-19` mentions shelling
  out to `` `oto check candidates` `` — the surrounding prose references the
  old flat script; `tests/test_occupancy_live_deck.py:6` explicitly names
  `` `check_candidates.py` ``, a deleted module (§5.4).
- `tests/phase1_harness.py` — suffix `_harness`.

Three suffixes for one role. Proposal: **unify to `tests/support_<area>.py`**:
`support_occupancy_gate.py` (was `occupancy_gate_common.py`),
`support_run_status.py` (was `run_status_fixture.py`),
`support_convergence.py` (was `phase1_harness.py`). `conftest.py` keeps its
job (markers, session fixtures) — no change. After the §3.1 renames, no test
file or helper mentions "phase1".

### 3.4 Where "phase"/"stage" vocabulary in tests conflicts with the present layout

- "the harness modules are imported flat, so they sit beside this file's parent" —
  stale pre-package-split narration in **8** test headers: `tests/run_status_fixture.py:20`,
  `tests/test_auto_prompt.py:22`, `tests/test_auto_reference_floor.py:23`,
  `tests/test_reference_tiers.py:22`, `tests/test_report_probe_glob.py:28`,
  `tests/test_report_family_case.py:26`, `tests/test_tensile_params.py:26`,
  `tests/test_thermal_gate.py:39`. Nothing is "imported flat" anymore; the
  package is `oto.*`.
- `tests/test_generate_candidates.py:21` — `sys.path.insert(0, str(REPO / "harness"))` —
  **the directory `harness/` no longer exists** (pre-split flat layout). Dead
  line.
- `tests/test_occupancy_live_deck.py:6` — "shell out to ``check_candidates.py``" —
  deleted module; the test actually invokes
  `[sys.executable, "-m", "oto", "check", "candidates"]`
  (`tests/test_occupancy_live_deck.py:109-115`).
- `tests/test_measurement_integrity.py:41,52,96` — "scheduler's byte table must
  agree...", "`scheduler table disagrees`", "disagrees between all_runs and
  scheduler" — the deleted pre-split `scheduler.py` named as if it were live.
- `tests/test_cell_attribution.py:16,57,164` — "gfx90c_common" / "scheduler" —
  pre-split module names in live test narration.
- `tests/test_thermal_gate.py:297` — "gfx90c_common.cube_side".
- `tests/test_legality_prior.py:5,187` — "`scheduler.validate_config`".
- `tests/test_mutation_arm.py:18`, `tests/test_synthesis_band_wiring.py:10`
  ("stub scheduler"), `tests/test_phase1_harness.py`'s `_StubScheduler` — "scheduler"
  survives as a variable name for the candidate-generator stand-in; harmless but
  reinforces the dead vocabulary (rename fixture class to `StubGenerator`/`StubEmitter`
  in the same sweep).
- `tests/test_auto_prompt.py:5` — docstring claims "the four --auto questions" while
  `oto/runners/auto_prompt.py:2` and `:48` say **five** — stale count in tests
  prose.
- `tests/conftest.py:117-120` — fine (loads `gfx90c` profile once per session).

### 3.5 Phase-vocabulary collision matrix (oto/ proper)

(table — as above, summarised earlier)

### 3.6 Full `tests/` inventory (80 files, one line each)

(support modules + test modules list — same content as earlier report)

---

## 4. `oto/tools/verifiers/` — are the `verify_*` names intuitive?

### 4.1 What's there (9 files) and what each does

(table — as above)

### 4.2 Honest appraisal

- The `verify_` prefix is verb-first — good instinct, retained.
- But the subjects are named by **implementation** or by **vague comparative
  nouns**, not by the property checked: "ast_equivalence" (AST of what? symbols),
  "method_equivalence" (vs signatures?), "gate_differential" (differential is
  not a subject), "config_writer" (a module name, not a property), "report_html"
  (an artifact, not a property).
- `verify_ast_equivalence` vs `verify_method_equivalence` are indistinguishable
  without reading both headers; they are the two halves of one "split-era
  equivalence" check.
- "evergreen" (46 occurrences across the 9 files) is repo-invented vocabulary
  meaning "re-runnable against any historical REF, nothing pinned" — it appears
  in `incomplete_work.md:87-97` and `docs/docstrings.md:90`, but no newcomer
  derives it from the word. It is also grammatically odd in identifiers
  (`_evergreen`, `oto_evergreen_scratch_` at `_evergreen.py:40`).
- `verify_all.py:25-30` lists five checks; `docs/skills/class_b_operator.md:34`
  calls them "(evergreen equivalence verifiers)". The suite's actual contract:
  **tree-vs-tree equivalence across the package split and any future refactor**.

### 4.3 Proposed consistent alternative (one scheme, applied uniformly)

Scheme: `verify_<subject>` where `<subject>` is the artifact whose bytes/values
must match between this tree and `--base REF` — i.e. names parallel to what the
diff actually compares, all verb-first, all one or two words:

| current | proposed | rationale |
|---|---|---|
| `verify_ast_equivalence.py` | `verify_symbols.py` | the subject is public symbols + signatures |
| `verify_method_equivalence.py` | `verify_methods.py` | the subject is method bodies |
| `verify_gate_differential.py` | `verify_gates.py` | the subject is gate verdicts |
| `verify_config_writer.py` | `verify_config_render.py` | what must match is the rendered (ok, reason) + YAML bytes, not "the writer" |
| `verify_report_html.py` | `verify_report_render.py` | what must match is the rendered HTML bytes |
| `verify_all.py` | **keep** (or `verify_equivalence.py` if preferred) | orchestrator; "all" is accurate |
| `_evergreen.py` | `ref_worktree.py` | helper that builds the detached REF worktree; drop both the underscore (§2) and the jargon |
| `_verdicts_worker.py` | `verdict_corpus.py` | emits the verdict corpus the gate check consumes |
| `__init__.py` | keep + add a docstring | consistency with every other package |

All call-sites, `CHECKS` in `verify_all.py:25-30`, `docs/skills/class_b_operator.md:34`
and `docs/docstrings.md:90` move with the rename. Public class/function names
(`probe_config`, `emit`, `main`) are untouched. If the project wants to retire
split-era semantics eventually (the MOVES/RESTRUCTURED tables from 2026-10), these
checks should instead be re-expressed as "REF vs tree" property tests — the names
above survive that transition; "ast/method equivalence" do not.

### 4.4 Should the split-era tables stay?

Out of scope for naming, recorded for the rename PR: `verify_ast_equivalence.py:28`
("gfx90c_common.py"), `:37,73,111,168-195` ("scheduler.py", "port_tensile.py") and
`verify_method_equivalence.py:3,118-120,180` ("port_tensile.py"),
`verify_config_writer.py:8-9,138-163` ("2824c2f", `sys.modules["port_tensile"] =
__import__("oto.runners.stage_cli")`) deliberately encode the pre-split tree so the
checks can run against old commits. This is not accidental legacy — it is the
entire point of an "evergreen" check. It stays; the *names* change, the
*tables* do not.

---

## 5. What else screams legacy

### 5.1 Device codename `gfx90c_*` in code — contract: only `oto/device/` or `profiles/` may hold it

Violations (i.e. `gfx90c` outside `oto/device/` and `profiles/`, excluding
docstring prose whose subject is the floor/reference or the device itself):

| location | content | verdict |
|---|---|---|
| `oto/tools/chart.py:2` | docstring "native gfx90c vs gfx900-spoofed (floor)" — device name in the module's *what it does* sentence | violates the ownership rule; reword to "native vs floor" |
| `oto/tools/chart.py:46,59,67` | `label="Native gfx90c (best)"`, title "Native gfx90c vs gfx900-spoofed", footnote | labels should come from `current_profile().codename` (the module already accepts `profile=`) |
| `oto/tools/chart.py:101` | default output `gfx90c_vs_spoof.png` | same; derive from profile or rename |
| `oto/cli/parser.py:350` | help example `oto chart --out gfx90c_vs_spoof.png` | same; reword example |
| `oto/tensile/decks.py:381` | comment "GPU-validated on gfx90c at both shapes" | mild; a provenance note, but should say "the reference device" or cite profile |
| `oto/tensile/decks.py:527` | same shape, "why": "Only ever 32. gfx900's dGPU tuning..." | `gfx900` = the floor; permitted |
| `oto/runners/paths.py:24-25` | `LEGACY_RUNS_DIR_NAME = "gfx90c_runs"` / `LEGACY_RESULTS_DIR_NAME = "gfx90c_results"` | **sanctioned exception** — this module is documented as the one home for the legacy directory names (`paths.py:2-9`) |
| `oto/tools/verifiers/verify_ast_equivalence.py:28` | `("gfx90c_common.py", ...)` in the MOVES table | historical filename, not a device fact; fine (§4.4) |
| `oto/tools/verifiers/_verdicts_worker.py:111,120,126,183` | synthetic `gfx90c_common` shim for pre-split REF | historical filename; fine |
| `oto/cli/doctor.py:208` | `"Add profiles/{codename}.json (see profiles/gfx90c.json)."` | points at the profile file; permitted (it names an artifact, not a fact) |
| `oto/device/*` + `profiles/gfx90c.json` | device facts | correct home |

So: real violations are **chart.py** (5 sites), **parser.py:350** (1), **decks.py:381** (1 comment).
`oto/tensile/decks.py` line 381 says `gfx90c` — a comment; the repo contract for names is about
*code-level identity*, but the same §8.1 reason applies: the device under test is not a fixed
constant of the codebase.

Tests are exempt in the same way they always are (they name the device under test; that's the
point of e.g. `tests/test_profile.py:14-20`, `tests/test_explicit_profile_threading.py:22-58`).
But three test *comments* carry the deleted `gfx90c_common` name — enumerated in §3.4.

### 5.2 `gfx900` (the reference floor) — fine

Pervasive (`shipped_library.py`, `library.py`, `best_library.py:356,407`, `synthesis.py:120`,
`mutator.py:119,302`, etc.). The floor is definitionally the gfx900 library; this is the one
place a device name may appear outside `oto/device/`. Not violations.

`oto/tensile/synthesis/manifest.py:297` and `oto/tensile/legality.py:516` call
`config.setdefault("Architecture", "gfx900")` — this is the floor's ISA triple baked into emitted
candidate configs rather than derived from `current_profile()`, which is a **design** anomaly
worth flagging to the main agent (out of scope for a naming audit, but it survives any rename).

### 5.3 `scheduler.py` / `port_tensile.py` / `wave_tile` / `candidate_prune` in live code

- `wave_tile`, `candidate_prune`: **zero** hits in `oto/` and `tests/` (verified by grep). Clean.
- `port_tensile.py` / `scheduler.py`:
  - `oto/runners/driver.py:50` — comment "`from port_tensile import _require_tensile_root`" —
    historical explanation of why the legacy aliases exist (`:53-54`); §8.1-tension. Move to
    `changelog.md` or reword to "the pre-package flat layout" without the filename.
  - `oto/cli/docs.py:19-40` and `docs/cli.md:696-704` — the `MIGRATION` table mapping
    `python3 port_tensile.py ...` → `oto ...`. This is a **live doc that names deleted
    machinery**, i.e. literally what claude.md §8.1 forbids ("must never reappear in code,
    configs, or docs"). Either amend §8.1 to exempt migration tables explicitly, or delete the
    table and its generated twin in `docs/cli.md`. Currently contradicted by policy.
  - `docs/implementation_plan.md:415` — historical plan text; borderline (plan docs are narrative).
  - `oto/tools/verifiers/*` — pervasive but intentional (§4.4). Keep.
  - `oto/tools/verifiers/verify_config_writer.py:159` — `sys.modules["port_tensile"] = ...` —
    execution shim, intentional.
  - `oto/tools/verifiers/verify_ast_equivalence.py:513` — `git cat-file -e {base}:scheduler.py` —
    intentional probe.
- Tests: `tests/test_measurement_integrity.py:41,52,96`, `tests/test_cell_attribution.py:164`,
  `tests/test_legality_prior.py:5,187`, `tests/test_thermal_gate.py:297` (`gfx90c_common`),
  `tests/test_cell_attribution.py:16,57` — stale deleted-module narration in live test files.

### 5.4 Deleted CLI/scripts named as if live in tests

- `tests/test_occupancy_live_deck.py:6` — its own docstring says the test shells out to
  `` `check_candidates.py` ``; the deleted flat script's name. The shell-out actually uses
  `[sys.executable, "-m", "oto", "check", "candidates"]`
  (`tests/test_occupancy_live_deck.py:109-115`).
- `tests/occupancy_gate_common.py:18-19` — mentions `` `oto check candidates` `` (current, fine);
  no deleted-module reference inside.
- `tests/test_cli_smoke.py:53` — `def test_check_candidates(...)` — name is fine (it invokes
  `oto check candidates`); no deleted reference inside.

### 5.5 Strings/refs that predate the package split

- `tests/test_generate_candidates.py:21` — dead `sys.path.insert(0, str(REPO / "harness"))` (§3.4).
- 8× "the harness modules are imported flat" (§3.4).
- `oto/__init__.py:1-4` — "Names are deliberately the ones the codebase used before the package
  split... so existing importers keep working across the move." — that migration is complete;
  the "historical flat names" shim is now itself legacy carrying cost. Not a rename; a removal
  candidate to flag to the main agent.
- `oto/README.md` — generated by `oto._map`; lists module docstrings; fine, regenerates on rename.

### 5.6 Non-`.py` strays inside `oto/`

- `oto/oto_script` — tracked, extensionless Python entry script duplicating `oto/__main__.py`
  (adds a `sys.path` bootstrap for "run from the repository root: ./oto doctor"). Not importable,
  not linted (`test_py_compile.py` globs `*.py`), not covered by guards. **Move to
  `bin/oto` (exists) or delete** — the canonical entry is `python3 -m oto` / the `oto` console
  script.
- `oto/tools/verifiers/drift_manifest.json` — data artifact consumed by the ast-equivalence
  check; fine where it is.
- `oto/README.md` — generated; fine.

### 5.7 `oto/device/__init__.py`'s "Refactor 2" prose

`oto/device/__init__.py:4` — "Refactor 2 seam: a driver that used to know gfx90c by name now
reads one DeviceProfile at startup" — milestone narration inside a module docstring (§3 rule:
name milestones only with a gloss, or drop; this one can drop "Refactor 2" entirely without
losing information).

---

## 6. Cross-cutting notes the rename PR must carry

1. **Two CLIs.** `oto/runners/stage_cli.py` (stage dispatch backend) + `oto/runners/stage_flags.py`
   vs `oto/cli/` (real CLI) + `oto/cli/flags.py`. Until the runner pair is renamed
   (`stage_cli.py`/`stage_flags.py`), every "flags" or "cli.py" reference in docs/tests is
   ambiguous. `docs/agent_reference.md:247` still tells humans to run
   `python3 -m oto.runners.stage_cli --report ...` — that path stays valid, but say so.
2. **`Stage`/`Phase-0`/`Option H Phase`/`Refactor N` vocabulary** lives in live docstrings
   (full grep list: §3.4, §3.5). None of it appears in filenames except the `tests/phase1_*`
   family and `tests/test_coverage_phase3.py`. A milestone→subject docstring sweep is the
   complete fix; file renames are confined to §3.1/§3.2.
3. **`ab_*` prefix** (five modules) — keep; A/B is the domain abbreviation repo-wide and every
   docstring glosses it on first use.
4. **`report_*.py` vs `*_status*.py`** — two report families, one flat namespace. After
   `report_build.py → build_status.py` and `report_figures.py → report_coverage.py`, the
   acceptance family is `report*` and the status family is `*run_status/render_status/
   build_status/status_common/ledger_state/run_plan*` — legible.
5. **`oto/tools/verifiers/__init__.py`** is the only docstring-less package root; every other
   `__init__.py` carries the Owns clause (every other one carries one; 13 packages + root). One-line fix.
6. **`oto/README.md`** regenerates from docstrings (`python3 -m oto._map`); run it after any
   rename or the README lists ghosts. `test_pyflakes`/`ruff` guards will catch dangling imports.
7. **`oto/oto_script`** (§5.6) — delete or relocate; it bypasses the package entry and the guards.
8. Rename PRs should be split by blast radius: (a) leaf-module renames (§1.4–1.13, no public API
   changes); (b) the runner CLI pair (touches `docs/cli.md`, `docs/agent_reference.md`);
   (c) the test-family renames (touches `tests/*` imports only); (d) the `_rows_*` collapse
   (optionally redesign, §2.3). Public API (`oto/__init__.py` re-exports) is untouched by (a)–(c).
9. Widening the guard: `tests/test_py_compile.py`, `test_ruff.py`, `test_pyflakes.py` cover all
   tracked `*.py`/`*.py` — a rename that misses a consumer fails them; `grep -rn "old_name"`
   per rename is mandatory anyway (claude.md §8.1: move the docstring with the code — the same
   rule applies to the `Does NOT own` mentions in neighbouring modules, which must be re-pointed).

---

## Appendix: the 20 worst names in the package (common-sense judgment)

1. `tests/phase1_harness.py` (with `tests/test_phase1_durability.py`, `test_phase1_overlay.py`,
   `test_phase1_readonly_gpu.py`, `test_phase1_writeback.py`) — reads as "the first benchmark
   phase"; actually Option H Phase 1's mutator/write-back fixtures. `tests/phase1_harness.py:2`.
2. `tests/test_coverage_phase3.py:1` — reads as pipeline phase 3; tests `oto/metrics/coverage.py`.
3. `oto/runners/stage_cli.py` — the *second* "cli"; its docstring (`:2`) still calls itself
   "the `python3 -m oto` command line" though that is `oto/cli/dispatch.py` today.
4. `oto/runners/stage_flags.py` — identical bare name to `oto/cli/flags.py`; the two CLIs' option sets
   are unrelated.
5. `oto/_map.py` — a hyphen from meaningless; a CLI-invoked README generator named like a private map.
6. `oto/_version.py` — "private" module imported by four other packages (`oto/__init__.py:34`,
   `oto/cli/flags.py:15`, `oto/cli/docs.py:16`, `oto/cli/commands.py:552`).
7. `oto/harness/rows_ladders.py` / `rows_frontier.py` / `rows_smallcells.py` — split tables whose
   meaning depends on import order (`rows_frontier.py:5-6`) and a word ("core") that says nothing.
8. `oto/metrics/_status_common.py` — private-marked module imported as the public status helper
   (`run_status.py:24` re-exports it).
9. `oto/tools/verifiers/_evergreen.py` — 46 occurrences of unexplained jargon; the module is a
   REF-worktree probe runner (`_evergreen.py:1-6`).
10. `oto/tools/verifiers/_verdicts_worker.py` — "worker" with no subject; it emits the verdict corpus.
11. `oto/tools/verifiers/verify_ast_equivalence.py` vs `verify_method_equivalence.py` —
    two files indistinguishable without opening both; name the halves (`verify_symbols.py`,
    `verify_methods.py`).
12. `oto/tools/all_runs.py` — squashed pre-refactor script name; `oto stats` maps to it.
13. `oto/harness/tensile_probe.py` — "oracle" is repo jargon for "ask Tensile itself"; every
    sibling verb is "probe" (`checks/tensile_build_probe.py`).
14. `oto/harness/occupancy_bounds.py` — "audit" promises a judgment; the file computes three
    physical bounds (`occupancy_bounds.py`).
15. `oto/metrics/report_build.py` — sits in the acceptance-report namespace but builds the
    *status* report; `build_status.py` dissolves the ambiguity.
16. `oto/metrics/policy.py` — a catch-all name for the per-cell run/retire policy; `cell_policy.py`.
17. `oto/runners/corpus_loaders.py` — promises analytics; delivers the driver's whole-corpus
    ingestion + retirement sweep (`corpus_loaders.py`).
18. `oto/agents/meta.py` — "meta" is a non-name; it is the orchestrator (`agents/orchestrator.py`).
    `oto/agents/harness_tools.py` (echoes `oto/harness/`) rides along in the same class.
19. `oto/tensile/library.py` vs `oto/tensile/shipped_library.py` — inverted pair: the manifest
    cache vs the binary .dat; newcomers swap them every time.
20. `oto/tensile/synthesis/donor_mutator.py` (+ `db_knobs.py`, `db_patterns.py`) — "db" = "the analysis
    kernel_db.json" is insider vocabulary; "donor" is the files' own word for the same things.

Honourable mentions (kept, with notes): `oto/yamlio.py`, `oto/runners/auto.py`,
`oto/metrics/read_thermals.py`, `oto/metrics/analytics.py` ("Stage 5"), `oto/tools/consolidate_*`
(vague "consolidate" family prefix, §1.12), `oto/metrics/render_status.py` vs
`oto/metrics/run_status.py` (fine), `oto/runners/reporting.py`, `oto/checks/candidates.py`,
`oto/checks/db.py`, `oto/tensile/library_parity.py` (fine), `oto/tools/verify_run.py` (namespace
clash with `tools/verifiers/`).

---

## Summary of counts

- Files inventoried: 162 `oto/*.py` (156 in 14 packages + 6 at root) + 80 `tests/*.py`.
- Proposed renames: 40 in `oto/` (§1 roll-up) + 9 in `tests/` (6 file renames: the `phase1_*`
  family and `test_coverage_phase3.py`; 3 support-module unifications, §3).
- Hard violations of the repo's device-fact contract: 3 sites (`oto/tools/chart.py` ×2-3,
  `oto/cli/parser.py:350`, `oto/tensile/decks.py:381` comment).
- Dead vocabulary in live names: the 5 `tests/phase1_*` files + `test_coverage_phase3.py`;
  "Stage 1..7"/"Phase-0" in `oto/` docstrings (§6.2).
- Empty package root: `oto/tools/verifiers/__init__.py` (0 bytes).
- Non-`.py` stray inside package: `oto/oto_script`.
- Zero hits: `wave_tile`, `candidate_prune` in `oto/`/`tests/`.

---

## Open questions for the owner

1. Does the `ab_*` prefix survive ("A/B" is the domain abbreviation, repo-wide) or does it
   become `acceptance_*`?
2. Are the `consolidate_*` files a family worth keeping, or should they become `deck_*` /
   `install_*`?
3. Does the `phase1_*` rename happen now, or wait until the Option H tests are touched next?
4. Should `_version.py` keep its underscore because PEP 562 / setuptools convention, or move
   to `version.py`? (Recommendation: move; the cross-package imports override the convention.)
5. Does the migration-table (`port_tensile.py` → `oto ...`) survive §8.1 of `claude.md`, or
   does §8.1 get amended to exempt migration tables?
6. Is `oto/oto_script` deleted, or relocated to `bin/oto`? (Recommendation: delete; `bin/oto`
   already exists and is the documented entry.)
7. Should the `verify_*` files be re-expressed as "REF vs tree property tests" once the
   split-era base is no longer reachable, or kept indefinitely?
8. Does the `_rows_*` collapse happen in this rename PR, or as a separate refactor (§2.3)?

---

## Appendix: the 20 worst names in the package (common-sense judgment)

... (full list already printed above in the agent's reply — reproduced in the plan as an
appendix with the same 20 entries.)

---

## What this plan does NOT do

- No rename has been applied. The tree is byte-identical to HEAD.
- No test has been updated, no import rewritten.
- No file was deleted, moved, or merged.
- The mass-replace safety net (`grep -rn "old_name"`) is described but not run.
- The docs ecosystem is audited but not changed by this plan; its cleanup is the
  owner's next instruction (§0 of this plan is the contract for it).

---

## Recommended migration order

1. **Phase A — leaf-module renames (§1.4–§1.13)**: 40 renames, no public API changes,
   no behaviour change. `oto/README.md` regenerated, `test_py_compile`/`ruff`/`pyflakes`
   are the guard. ~one commit per package (8-12 commits). **Safest first step.**
2. **Phase B — the runner CLI pair** (`runners/stage_cli.py` → `stage_cli.py`,
   `runners/stage_flags.py` → `stage_flags.py`): touches `docs/cli.md`, `docs/agent_reference.md`,
   `oto/cli/commands.py`, `oto/cli/parser.py` help strings. One commit. Run `oto help --write`
   and `tests/test_docs_cli.py` to verify the doc stays byte-identical.
3. **Phase C — test family renames** (5 `phase1_*` files + `test_coverage_phase3.py` →
   the `support_*`/`test_*` names): touches test imports only. One commit. Full suite green.
4. **Phase D — the `_rows_*` collapse (optional)**: collapse into `candidate_rows.py` or a
   `rows/` subpackage with explicit ordered init. This is a *design* change, not a rename;
   do it only if the maintainers want to retire the "import order matters" invariant. One
   commit, with a property test that the order is established by construction.
5. **Phase E — docstring/comment sweep** (§5.3, §6.2): milestone vocabulary → subject
   vocabulary in live docstrings; `oto/device/__init__.py` drops "Refactor 2"; `oto/cli/docs.py`
   migration table decided (§5.3); `oto/__init__.py` "historical flat names" note either
   justified or removed.
6. **Phase F — stray cleanup**: delete `oto/oto_script` (or move to `bin/`); add a docstring
   to `oto/tools/verifiers/__init__.py`; fix the 3 `chart.py` + `parser.py:350` + `decks.py:381`
   device-name violations; document `manifest.py:297`/`legality.py:516`'s `gfx900` baked-in
   default.
7. **Phase G — `consolidate_*` family decision** (owner call, open question 2).

After Phase A the package is already legible. Phases B–G are incremental and each
independently shippable.

---

## Summary

- **297 tracked files inventoried** (165 `oto/`, 80 `tests/`, 41 root/docs/plans/archive).
- **40 module renames proposed** in `oto/`; 9 in `tests/`; 13 support-module renames folded into
  the same count.
- **Hard violations of the repo's device-fact contract: 3 sites** (chart.py ×2-3,
  parser.py:350, decks.py:381 comment) — all trivial rewordings.
- **Dead vocabulary in live names**: the 5 `tests/phase1_*` files + `test_coverage_phase3.py`;
  "Stage 1..7"/"Phase-0" in `oto/` docstrings (§6.2).
- **Empty package root**: `oto/tools/verifiers/__init__.py` (0 bytes).
- **Non-`.py` stray inside package**: `oto/oto_script`.
- **Zero hits**: `wave_tile`, `candidate_prune` in `oto/`/`tests/` (clean).
- **`ab_*` prefix**: keep; `report_*/` families: split after the renames.
- **No functional change is proposed anywhere.** Public API (`oto/__init__.py` re-exports)
  is untouched by Phases A–C.
- **Nothing has been applied.** This file is the proposal; implementation is a later task.

---

## Appendix: the 20 worst names (common-sense judgment, summarised)

1. `tests/phase1_harness.py` (reads as "the first benchmark phase"; it is Option H Phase 1's mutator/write-back fixtures) — `tests/phase1_harness.py:2`.
2. `tests/test_coverage_phase3.py:1` — reads as "pipeline phase 3"; tests `oto/metrics/coverage.py`.
3. `oto/runners/stage_cli.py` — the *second* "cli"; its own docstring (`:2`) claims "the `python3 -m oto` command line" though that entry is `oto/cli/dispatch.py`.
4. `oto/runners/stage_flags.py` — identical bare name to `oto/cli/flags.py`.
5. `oto/_map.py` — a hyphen from meaningless; a CLI-invoked README generator named like a private map.
6. `oto/_version.py` — "private" module imported by four other packages (`oto/__init__.py:34`, `oto/cli/flags.py:15`, `oto/cli/docs.py:16`, `oto/cli/commands.py:552`).
7. `oto/harness/rows_ladders.py` / `rows_frontier.py` / `rows_smallcells.py` — split tables whose meaning depends on import order (`rows_frontier.py:5-6`) and a word ("core") that says nothing.
8. `oto/metrics/_status_common.py` — private-marked module imported as the public status helper (`run_status.py:24` re-exports it).
9. `oto/tools/verifiers/_evergreen.py` — 46 occurrences of unexplained jargon; the module is a REF-worktree probe runner (`_evergreen.py:1-6`).
10. `oto/tools/verifiers/_verdicts_worker.py` — "worker" with no subject; it emits the verdict corpus.
11. `oto/tools/verifiers/verify_ast_equivalence.py` vs `verify_method_equivalence.py` — two files indistinguishable without opening both; name the halves (`verify_symbols.py`, `verify_methods.py`).
12. `oto/tools/all_runs.py` — squashed pre-refactor script name; `oto stats` maps to it.
13. `oto/harness/tensile_probe.py` — "oracle" is repo jargon for "ask Tensile itself"; every sibling verb is "probe" (`checks/tensile_build_probe.py`).
14. `oto/harness/occupancy_bounds.py` — "audit" promises a judgment; the file computes three physical bounds (`occupancy_bounds.py`).
15. `oto/metrics/report_build.py` — sits in the acceptance-report namespace but builds the *status* report; `build_status.py` dissolves the ambiguity.
16. `oto/metrics/policy.py` — a catch-all name for the per-cell run/retire policy; `cell_policy.py`.
17. `oto/runners/corpus_loaders.py` — promises analytics; delivers the driver's whole-corpus ingestion + retirement sweep (`corpus_loaders.py`).
18. `oto/agents/meta.py` — "meta" is a non-name; it is the orchestrator (`agents/orchestrator.py`). `oto/agents/harness_tools.py` (echoes `oto/harness/`) rides along in the same class.
19. `oto/tensile/library.py` vs `oto/tensile/shipped_library.py` — inverted pair: the manifest cache vs the binary .dat; newcomers swap them every time.
20. `oto/tensile/synthesis/donor_mutator.py` (+ `db_knobs.py`, `db_patterns.py`) — "db" = "the analysis kernel_db.json" is insider vocabulary; "donor" is the files' own word for the same things.

---

## 7. Docs ecosystem audit (from `docs_ecosystem.md`)

The docs ecosystem has 43 tracked markdown docs (root 21, `docs/` 19 incl.
skills, `plans/` 4, `archive/` 5) plus 5 JSON docs. 30 are live/essential;
7 are frozen evidence/prior layer; 4 are transitional plan docs; 2 are
research inputs.

### 7.1 Dead-symbol citations in live docs (15 files, 7 essential)

The following live docs cite deleted modules or retired files. They are not
violations of the same kind as the code-level device-fact leaks (these are
historical pointers, which the docs ecosystem rules permit in the right place),
but the phrasing should be reworded to point at the replacement:

| file | dead symbol cited | fix |
|---|---|---|
| `docs/cli.md` (8) | `port_tensile.py --auto` etc. (in the MIGRATION table) | exempt the migration table explicitly in `claude.md` §8.1, or delete the table |
| `plans/REFACTOR_2_UNIVERSAL_GPU.md` (4) | `gfx90c_common.py`, `peaks.py`, `resolvers.py` | frozen plan doc; only used as history; leave or archive |
| `plans/CLI_UX_REWORK.md` (4) | `port_tensile.py` shorthand | archive (status: implemented) |
| `archive/prior_insights.md` (3) | `gfx90c_common.py`, `proposed_fixes.md`, `changes_kb.md`, `run_gfx90c_suite.sh` | sanctioned prior-knowledge copy; keep as-is; the cites are the *point* of the file |
| `docs/research/kernel_tuning.md` (2) | `gates/assembly.py`, `scheduler.py` (as shorthand) | reword to `oto/tensile/gates/assembly.py` + full path |
| `archive/prior_research_archive.md` (1) | `gfx90c_common.py`, `AsmCaps.py`, `auto_retire.py` | sanctioned prior-knowledge copy; keep as-is |
| `docs/implementation_plan.md` (1) | `scheduler.py` shorthand | reword or archive |
| `changelog.md` (65) | all of the above | append-only history; keep verbatim |

The MIGRATION-table case in `docs/cli.md` is the one that needs an explicit
policy decision (open question 5 in §9).

### 7.2 Ephemeral-state citations in live docs (9 files)

Files that cite `/tmp/`, `todo.txt`, `command.txt`, concrete run ids, or
"this session":

| file | evidence |
|---|---|
| `docs/audit_register.md` | `:155` (`/tmp/opencode/*_fixed.py`) |
| `docs/operator_runbook.md` | `:221` (`command.txt`) |
| `docs/implementation_plan.md` | `:459,480,495,496,579` |
| `docs/potential_configs.md` | `:2431,3301,3312,3349` |
| `docs/results.md` | `:22,92,99,106,123,147,269` (run ids) |
| `docs/search_philosophy.md` | `:147` (run id) |
| `changelog.md` | `:25,38,90,243,334,1135,...` (33 hits) |
| `claude.md` | `:175,483,487,491,492,495,533` (policy refs) |
| `archive/prior_research_archive.md` | `:...` (history refs) |

The policy-only references (`claude.md`, `docs/operator_runbook.md`) are
guardrails, not data citations; the rest are live ephemeral-state citations
that violate the docs-ecosystem boundary rule. The largest scrub is the
changelog (33 `/tmp` hits, 8 `command.txt` hits, 14 dead-module hits) —
append-only history, so the scrub must be careful not to rewrite history,
only to genericize the machine-local portion (`/tmp/opencode/foo.py` →
`<scratch>/foo.py`).

### 7.3 Consolidation recommendations (docs ecosystem)

| action | files | rationale |
|---|---|---|
| **Merge** | `archive/prior_insights.md` + `archive/prior_research_archive.md` → `archive/prior_campaign_20260913.md` | two sanctioned copies of the same prior-campaign materials; one is a redundant copy |
| **Merge** | `docs/search_philosophy.md` + `docs/research/complex_gemm_brief.md` into `docs/research/kernel_tuning.md` | philosophy + complex-GEMM sections already overlap; `docs/research/kernel_tuning.md` is the owner of both |
| **Absorb** | `incomplete_work.md` open items into `docs/implementation_plan.md` §open register; drop `incomplete_work.md` | the register is a to-do list, not a status |
| **Split** | `docs/potential_configs.md` (3440 lines) → `candidate_deck.md` + `candidate_research.md` | deck + decisions vs research integration; the file is too big to navigate |
| **Split** | `changelog.md` (4280 lines) → `changelog.md` (current year) + `archive/changelog_pre_2026-11.md` | keep the current-year log readable; keep the append-only chain intact |
| **Archive** | `plans/CLI_UX_REWORK.md`, `plans/REFACTOR_2_UNIVERSAL_GPU.md`, `plans/test_optimization.md` → `archive/plans/` | all three are `IMPLEMENTED`/`EXECUTED`; live pointer in `changelog.md` is enough |
| **Bundle** | `archive/corpus.pass1_20261014.md`, `corpus2.pass2_20261014.md`, `corpus3.pass3_20261014.md`, `RESEARCH_PROMPT3.pass3_20261014.md`, `potential_configs.pre_rewrite_20261014.md` → `archive/research_corpus_20261014.md` | five frozen evidence snapshots; one bundle is easier to reference |
| **Move** | `docs/design_language.md` → `docs/ui/design_language.md` (or drop from index) | unrelated to kernel-tuning content; lives in the docs ecosystem by accident |
| **Rename** | `context.md` → `rocm_coupling_context.md`; `docs/shipped_floor_contract.md` → `shipped_footprint.md` (optional); `incomplete_work.md` → `open_work.md` (if not merged); `docs/potential_configs.md` → `candidate_deck.md` (if split) | generic names |
| **Scrub** | all live docs: `/tmp/opencode/*`, `/home/netherquark/*`, `/opt/rocm` (where not env documentation), `todo.txt`/`command.txt`, deleted-module shorthands | docs-ecosystem boundary rule |

### 7.4 Docs ecosystem — non-`.md` strays

- `oto/oto_script` — tracked stray duplicate of `bin/oto` (see §5.6 of python_layout.md and §8.2 below).
- `docs/docs_index.json` — generated; 39 entries vs 43 tracked md files. Either include all live docs or mark exclusions explicitly.
- `gfx90c_vs_spoof.png` — generated chart artifact, not a registered doc; move to `gfx90c_results/` or delete.

---

## 8. Root & config audit (from `root_config.md`)

### 8.1 Per-file verdicts (root/config)

| File | Verdict | Reason | Evidence |
|---|---|---|---|
| `README.md` | keep | Landing/orientation doc with TOC; not a log | `README.md:1`, `README.md:11` |
| `LICENSE` | keep | GPL-3.0 license text | `LICENSE:1` |
| `.gitignore` | keep (fix) | Ignores `archive/` while 4 `archive/*.md` are tracked; also carries forward-looking dead patterns (`*.bak2`, `*.pre_*_fix_*`) | `.gitignore:100`, `git ls-files archive/` |
| `.env.example` | keep (update) | Missing API/agent vars used by code (see Q4) | `.env.example:1`, `oto/agents/research.py:56` |
| `ruff.toml` | keep | Pinned guard config consumed by `tests/test_ruff.py` | `ruff.toml:1` |
| `pytest.ini` | keep | Suite config (testpaths/markers) | `pytest.ini:1` |
| `requirements.txt` | keep | Runtime + dev deps | `requirements.txt:1` |
| `bin/oto` | keep | Canonical shell entry point; delegates to `python3 -m oto` | `bin/oto:1-12` |
| `oto/oto_script` | delete | Unreferenced leftover from R2-cli Phase 2; no imports anywhere; broken `sys.path` target | `oto/oto_script:1`, `git log -- oto/oto_script` |
| `archive/prior_insights.md` | keep | Sanctioned frozen prior conclusions | `docs/README.md` registry row; `claude.md:221` |
| `archive/prior_research_archive.md` | keep | Sanctioned frozen prior conclusions | `docs/README.md` registry row; `claude.md:221` |
| `gfx90c_vs_spoof.png` | delete (or move to `gfx90c_results/`) | Generated chart artifact (`oto chart`), not source; not a registered doc | `oto/tools/chart.py:101`, `docs/cli.md:154` |
| `docs/gfx90c_tuning_guide.md` | keep | Sanctioned root docs-ecosystem file | `docs/README.md` registry row |
| `docs/gfx90c_theoretical_limits.md` | keep | Sanctioned root docs-ecosystem file (acceptance authority) | `docs/README.md` registry row |
| `archive/*` | keep (frozen) | Frozen evidence; `RESEARCH_PROMPT3.pass3_20261014.md` has no live prose refs (only docs index); the three `corpus*.md` are referenced by `docs/research/kernel_tuning.md` / `docs/knowledge_base.md` | `docs/docs_index.json:192` |

### 8.2 Docs-ecosystem boundary violations (tracked files)

Files that reference ephemeral state (`todo.txt`, `command.txt`, concrete run
ids, `/tmp/` paths, "this session"):

| File | Evidence |
|---|---|
| `docs/audit_register.md` | `docs/audit_register.md:155` (`/tmp/opencode/*_fixed.py`) |
| `changelog.md` | `changelog.md:25,38,90,243,334,1135,1336,1373,1395,1479,1538,1648,1830,2134,2351,2393,2400,2442,2448` |
| `claude.md` | `claude.md:175,483,487,491,492,495,533` (policy refs to `todo.txt`/`command.txt`/`/tmp/opencode`) |
| `docs/comparability.md` | `docs/comparability.md:57` (concrete run id `gfx900_ref_locked_52149f315d`) |
| `docs/operator_runbook.md` | `docs/operator_runbook.md:221` (`command.txt`) |
| `docs/implementation_plan.md` | `docs/implementation_plan.md:459,480,495,496,579` |
| `docs/potential_configs.md` | `docs/potential_configs.md:2431,3301,3312,3349` |
| `docs/results.md` | `docs/results.md:22,92,99,106,123,147,269` (concrete run ids) |
| `docs/search_philosophy.md` | `docs/search_philosophy.md:147` (concrete run id) |

Policy-only references (`claude.md`, `docs/operator_runbook.md`) are guardrails,
not data citations; the rest are live ephemeral-state citations that violate the
"docs ecosystem never references ephemeral state" rule.

### 8.3 Headline answers (root/config)

1. **`bin/oto` vs `oto/cli`:** `bin/oto` is the sole user-facing shell shim
   (`python3 -m oto`); `oto/cli/dispatch.py` owns command dispatch.
   `oto/oto_script` duplicates neither usefully and should be deleted.
2. **`oto/oto_script` tracked intentionally?** No — it is an unreferenced leftover
   from the R2-cli Phase 2 commit (copied from the deleted root `oto.py`); nothing
   imports it. Verdict: delete.
3. **`gfx90c_*` files:** `docs/gfx90c_tuning_guide.md` and `docs/gfx90c_theoretical_limits.md`
   are sanctioned (registered in `docs/README.md`). `gfx90c_vs_spoof.png` is an
   unregistered generated artifact → delete or move to `gfx90c_results/`.
4. **`.env.example` missing:** `OTO_API_KEY`, `OTO_API_ENDPOINT`, `OTO_API_MODEL`,
   `OTO_API_MAX_TOKENS`, `OTO_API_TIMEOUT`, `OTO_ARCHS`, `OTO_NO_AUTO_KERNEL_DB_REBUILD`,
   `OTO_PROFILE_SHIM`, `OTO_TENSILE_CLIENT` (and dev-only `OTO_GUARD_FILES`).
5. **README.md:** A landing/orientation page (title explained at `README.md:1-7`),
   not a log — but its `oto` link points at the package dir, not `bin/oto`.
6. **`archive/*` with no live references:** `RESEARCH_PROMPT3.pass3_20261014.md`
   has no prose references (only the docs registry index). The three `corpus*.md`
   files are referenced by `docs/research/kernel_tuning.md` / `docs/knowledge_base.md`.
   Untracked `archive/` contents are gitignored by design.

### 8.4 `.gitignore` note

Ignores `archive/` while 4 `archive/*.md` are tracked — that's a feature, not a
bug (tracked evidence vs untracked working files). Also carries forward-looking
dead patterns (`*.bak2`, `*.pre_*_fix_*`); harmless but noisy.

---

## 9. The tests audit (from `tests_names.md`)

### 9.1 Per-file verdict summary

- 80 test files inventoried; 74 are KEEP (name matches subject), 6 RENAME:
  - `tests/test_phase1_durability.py` → `tests/test_proposal_durability.py`
  - `tests/test_phase1_overlay.py` → `tests/test_overlay_merge.py`
  - `tests/test_phase1_readonly_gpu.py` → `tests/test_readonly_reporting.py`
  - `tests/test_phase1_writeback.py` → `tests/test_outcome_writeback.py`
  - `tests/test_coverage_phase3.py` → `tests/test_coverage.py`
  - `tests/test_interactive_keys.py` → `tests/test_run_keys.py`
- 4 support modules unified under `support_*`:
  - `tests/occupancy_gate_common.py` → `tests/support_occupancy_gate.py`
  - `tests/phase1_harness.py` → `tests/support_convergence.py`
  - `tests/run_status_fixture.py` → `tests/support_run_status.py`
- `conftest.py` marker scheme well-documented; gaps: hardcoded `PREFLIGHT_FILES`
  tuple drift risk, no test currently carries `serial` (prospective only).

### 9.2 Consolidation opportunities (tests)

- Split `test_interactive_keys.py` into `test_run_keys.py` + fold CLI option
  surface into `test_cli_smoke.py`.
- Merge `test_auto_prompt.py` + `test_auto_reference_floor.py` → `test_auto_mode.py`.
- Optionally merge `test_run_status_live.py` + `test_run_status_report.py` over
  `support_run_status.py`.
- Telemetry/run-integrity cluster (`test_verify_run.py`, `test_measurement_integrity.py`,
  `test_tensile_params.py`) acceptable as-is.

### 9.3 Appendix: 10 best-named / 10 worst-named test files

Best: `test_paths.py`, `test_protocol.py`, `test_shape_order.py`, `test_toolchain.py`,
`test_toolchain_layout.py`, `test_thermal_gate.py`, `test_visual_check.py`,
`test_derive.py`, `test_docs_index.py`, `test_profile.py`.

Worst: `test_phase1_durability.py`, `test_phase1_overlay.py`,
`test_phase1_readonly_gpu.py`, `test_phase1_writeback.py`,
`test_coverage_phase3.py`, `test_interactive_keys.py`,
`test_measurement_integrity.py`, `test_agents.py`, `test_db_mutator.py`,
`test_ab_audit.py`.

---

## 10. Consolidated rename table (old → new → reason → risk)

### 10.1 `oto/` modules (40 renames, §1 of python_layout.md)

| old | new | reason | risk |
|---|---|---|---|
| `oto/_version.py` | `oto/version.py` | cross-package imports violate private-marker intent | low |
| `oto/_map.py` | `oto/inventory.py` | CLI entry (`python3 -m oto._map`) hidden behind underscore | low |
| `oto/runners/stage_cli.py` | `oto/runners/stage_cli.py` | collides with `oto/cli/` | medium (docs/cli.md) |
| `oto/runners/stage_flags.py` | `oto/runners/stage_flags.py` | collides with `oto/cli/flags.py` | medium |
| `oto/runners/reference_floor.py` | `oto/runners/reference_floor.py` | "reference" alone doesn't say which reference | low |
| `oto/runners/corpus_loaders.py` | `oto/runners/corpus_loaders.py` | promises analytics; delivers driver ingestion | low |
| `oto/runners/library_build.py` | `oto/runners/library_build.py` | collides with `oto/tensile/synthesis/` | medium |
| `oto/metrics/policy.py` | `oto/metrics/cell_policy.py` | catch-all name | low |
| `oto/metrics/report_build.py` | `oto/metrics/build_status.py` | acceptance-report-family collision | low |
| `oto/metrics/report_figures.py` | `oto/metrics/report_coverage.py` | "figures" promises plotting; owns a coverage section | low |
| `oto/metrics/_status_common.py` | `oto/metrics/status_common.py` | inconsistent with public sibling `render_status.py` | low |
| `oto/tensile/library.py` | `oto/tensile/shipped_manifest.py` | inverted pair with `shipped_library.py` | medium |
| `oto/tensile/gates/ldspad_gate.py` | `oto/tensile/gates/ldspad.py` | redundant `_gate` suffix | low |
| `oto/tensile/gates/occupancy_common.py` | `oto/tensile/gates/gate_common.py` | named for one of two consumers | low |
| `oto/tensile/synthesis/donor_mutator.py` | `oto/tensile/synthesis/donor_mutator.py` | "db" is insider shorthand | low |
| `oto/tensile/synthesis/donor_knobs.py` | `oto/tensile/synthesis/donor_knobs.py` | same | low |
| `oto/tensile/synthesis/donor_patterns.py` | `oto/tensile/synthesis/donor_patterns.py` | same | low |
| `oto/harness/rows_ladders.py` | `oto/harness/rows_ladders.py` | underscore-private yet effectively public | medium (import-order fragility) |
| `oto/harness/rows_frontier.py` | `oto/harness/rows_frontier.py` | same | medium |
| `oto/harness/rows_smallcells.py` | `oto/harness/rows_smallcells.py` | same | medium |
| `oto/harness/deck_probe.py` | `oto/harness/deck_probe.py` | subject is the build probe, not "checking" | low |
| `oto/harness/tensile_probe.py` | `oto/harness/tensile_probe.py` | "oracle" is repo jargon; siblings are "probe" | low |
| `oto/harness/occupancy_bounds.py` | `oto/harness/occupancy_bounds.py` | "audit" promises a judgment; computes physical bounds | low |
| `oto/agents/harness_tools.py` | `oto/agents/agent_tools.py` | echoes `oto/harness/` package | low |
| `oto/agents/meta.py` | `oto/agents/orchestrator.py` | "meta" is a non-name | low |
| `oto/checks/candidates.py` | `oto/checks/deck_legality.py` | bare "candidates" indistinguishable from generation | low |
| `oto/checks/db.py` | `oto/checks/registry_audit.py` | "db" says nothing | low |
| `oto/tools/all_runs.py` | `oto/tools/all_runs.py` | squashed pre-refactor script name | low |
| `oto/tools/potential_configs.py` | `oto/tools/potential_configs.py` | trailing `_gen` is the version-suffix smell | low |
| `oto/tools/verify_run.py` | `oto/tools/corpus_audit.py` | namespace clash with `tools/verifiers/`; it audits the corpus | low |
| `oto/tools/verifiers/verify_ast_equivalence.py` | `oto/tools/verifiers/verify_symbols.py` | subject is public symbols + signatures | medium (verifier tables) |
| `oto/tools/verifiers/verify_method_equivalence.py` | `oto/tools/verifiers/verify_methods.py` | subject is method bodies | medium |
| `oto/tools/verifiers/verify_gate_differential.py` | `oto/tools/verifiers/verify_gates.py` | subject is gate verdicts | medium |
| `oto/tools/verifiers/verify_config_writer.py` | `oto/tools/verifiers/verify_config_render.py` | subject is the rendered output | medium |
| `oto/tools/verifiers/verify_report_html.py` | `oto/tools/verifiers/verify_report_render.py` | subject is rendered HTML bytes | medium |
| `oto/tools/verifiers/_evergreen.py` | `oto/tools/verifiers/ref_worktree.py` | drop the underscore + the "evergreen" jargon | low |
| `oto/tools/verifiers/_verdicts_worker.py` | `oto/tools/verifiers/verdict_corpus.py` | "worker" with no subject | low |

### 10.2 `tests/` renames (9 renames)

- `tests/phase1_harness.py` → `tests/support_convergence.py`
- `tests/test_phase1_durability.py` → `tests/test_proposal_durability.py`
- `tests/test_phase1_overlay.py` → `tests/test_overlay_merge.py`
- `tests/test_phase1_readonly_gpu.py` → `tests/test_readonly_reporting.py`
- `tests/test_phase1_writeback.py` → `tests/test_outcome_writeback.py`
- `tests/test_coverage_phase3.py` → `tests/test_coverage.py`
- `tests/occupancy_gate_common.py` → `tests/support_occupancy_gate.py`
- `tests/run_status_fixture.py` → `tests/support_run_status.py`
- `tests/test_interactive_keys.py` → `tests/test_run_keys.py`

### 10.3 Docs/root renames and moves

- `context.md` → `rocm_coupling_context.md` (generic name)
- `docs/shipped_floor_contract.md` → `shipped_footprint.md` (optional)
- `incomplete_work.md` → `open_work.md` (or merge into `docs/implementation_plan.md`)
- `docs/potential_configs.md` → split into `candidate_deck.md` + `candidate_research.md`
- `changelog.md` → split into `changelog.md` (current year) + `archive/changelog_pre_2026-11.md`
- `plans/CLI_UX_REWORK.md`, `plans/REFACTOR_2_UNIVERSAL_GPU.md`, `plans/test_optimization.md` → `archive/plans/`
- `docs/design_language.md` → `docs/ui/design_language.md` or drop from index
- `oto/oto_script` → delete (move to `bin/oto` if needed)
- `gfx90c_vs_spoof.png` → delete or move to `gfx90c_results/`
- `archive/prior_insights.md` + `archive/prior_research_archive.md` → `archive/prior_campaign_20260913.md`
- `docs/search_philosophy.md` + `docs/research/complex_gemm_brief.md` → merge into `docs/research/kernel_tuning.md`
- `archive/corpus*.md` + `archive/RESEARCH_PROMPT3.pass3_20261014.md` + `archive/potential_configs.pre_rewrite_20261014.md` → `archive/research_corpus_20261014.md`

---

## 11. Open questions for the owner (carried from the python_layout audit + this pass)

1. Does the `ab_*` prefix survive ("A/B" is the domain abbreviation, repo-wide) or does it
   become `acceptance_*`?
2. Are the `consolidate_*` files a family worth keeping, or should they become `deck_*` /
   `install_*`?
3. Does the `phase1_*` rename happen now, or wait until the Option H tests are touched next?
4. Should `_version.py` keep its underscore because PEP 562 / setuptools convention, or move
   to `version.py`? (Recommendation: move; cross-package imports override the convention.)
5. Does the migration-table (`port_tensile.py` → `oto ...`) survive `claude.md` §8.1, or
   does §8.1 get amended to exempt migration tables?
6. Is `oto/oto_script` deleted, or relocated to `bin/oto`? (Recommendation: delete; `bin/oto`
   already exists and is the documented entry.)
7. Should the `verify_*` files be re-expressed as "REF vs tree property tests" once the
   split-era base is no longer reachable, or kept indefinitely?
8. Does the `_rows_*` collapse happen in this rename PR, or as a separate refactor (§2.3)?
9. Should `docs/potential_configs.md` be split (3440 lines, deck + research) or kept as the
   canonical single file?
10. Should `changelog.md` be split (4280 lines) into current-year + archive?
11. Does the docs ecosystem scrub of `/tmp` / `todo.txt` / `command.txt` / run-id references
    happen in this PR or a separate docs-only PR?
12. Does `docs/design_language.md` move to `docs/ui/design_language.md` or stay at the top level?

---

## 12. Migration order (seven phases, each independently shippable)

1. **Phase A — leaf-module renames** (§1.4–§1.13): 40 renames in `oto/`, no public API
   changes, no behaviour change. `oto/README.md` regenerated; `test_py_compile`/`ruff`/
   `pyflakes` are the guard. ~8-12 commits, one per package. **Safest first step.**
2. **Phase B — the runner CLI pair**: `runners/stage_cli.py` → `stage_cli.py`,
   `runners/stage_flags.py` → `stage_flags.py`. Touches `docs/cli.md`,
   `docs/agent_reference.md`, `oto/cli/commands.py`, `oto/cli/parser.py` help strings.
   One commit. Run `oto help --write` and `tests/test_docs_cli.py` to verify the doc
   stays byte-identical.
3. **Phase C — test family renames**: the 5 `phase1_*` files + `test_coverage_phase3.py`
   → the `support_*`/`test_*` names; 3 support-module unifications. Touches `tests/*`
   imports only. One commit. Full suite green.
4. **Phase D — the `_rows_*` collapse (optional)**: collapse into `candidate_rows.py` or a
   `rows/` subpackage with explicit ordered init. This is a *design* change, not a rename;
   do it only if the maintainers want to retire the "import order matters" invariant. One
   commit, with a property test that the order is established by construction.
5. **Phase E — docstring/comment sweep**: milestone vocabulary → subject vocabulary in live
   docstrings; `oto/device/__init__.py` drops "Refactor 2"; `oto/cli/docs.py` migration
   table decided (open question 5); `oto/__init__.py` "historical flat names" note either
   justified or removed.
6. **Phase F — stray cleanup**: delete `oto/oto_script` (or move to `bin/`); add a docstring
   to `oto/tools/verifiers/__init__.py`; fix the 3 `chart.py` + `parser.py:350` + `decks.py:381`
   device-name violations; document `manifest.py:297`/`legality.py:516`'s `gfx900` baked-in
   default.
7. **Phase G — docs ecosystem consolidation**: apply the merge/rename/split/archive plan
   in §7; scrub ephemeral references per §7.3; regenerate `docs/docs_index.json`.

After Phase A the package is already legible. Phases B–G are incremental and each
independently shippable.

---

## Summary of counts

- Files inventoried: 297 tracked files (165 `oto/`, 80 `tests/`, 41 root/docs/plans/archive).
- Proposed renames: 40 in `oto/` (§1 roll-up) + 9 in `tests/` (6 file renames + 3 support-module
  unifications, §3).
- Hard violations of the repo's device-fact contract: 3 sites (`oto/tools/chart.py` ×2-3,
  `oto/cli/parser.py:350`, `oto/tensile/decks.py:381` comment).
- Dead vocabulary in live names: the 5 `tests/phase1_*` files + `test_coverage_phase3.py`;
  "Stage 1..7"/"Phase-0" in `oto/` docstrings (§6.2).
- Empty package root: `oto/tools/verifiers/__init__.py` (0 bytes).
- Non-`.py` stray inside package: `oto/oto_script`.
- Zero hits: `wave_tile`, `candidate_prune` in `oto/`/`tests/` (clean).
- `ab_*` prefix: keep; `report_*/` families: split after the renames.
- No functional change is proposed anywhere. Public API (`oto/__init__.py` re-exports)
  is untouched by Phases A–C.
- Nothing has been applied. This file is the proposal; implementation is a later task.

---

## Appendix: the 20 worst names (common-sense judgment, summarised)

1. `tests/phase1_harness.py` (reads as "the first benchmark phase"; it is Option H Phase 1's mutator/write-back fixtures) — `tests/phase1_harness.py:2`.
2. `tests/test_coverage_phase3.py:1` — reads as pipeline phase 3; tests `oto/metrics/coverage.py`.
3. `oto/runners/stage_cli.py` — the *second* "cli"; its docstring (`:2`) still calls itself "the `python3 -m oto` command line" though that is `oto/cli/dispatch.py` today.
4. `oto/runners/stage_flags.py` — identical bare name to `oto/cli/flags.py`; the two CLIs' option sets are unrelated.
5. `oto/_map.py` — a hyphen from meaningless; a CLI-invoked README generator named like a private map.
6. `oto/_version.py` — "private" module imported by four other packages (`oto/__init__.py:34`, `oto/cli/flags.py:15`, `oto/cli/docs.py:16`, `oto/cli/commands.py:552`).
7. `oto/harness/rows_ladders.py` / `rows_frontier.py` / `rows_smallcells.py` — split tables whose meaning depends on import order (`rows_frontier.py:5-6`) and a word ("core") that says nothing.
8. `oto/metrics/_status_common.py` — private-marked module imported as the public status helper (`run_status.py:24` re-exports it).
9. `oto/tools/verifiers/_evergreen.py` — 46 occurrences of unexplained jargon; the module is a REF-worktree probe runner (`_evergreen.py:1-6`).
10. `oto/tools/verifiers/_verdicts_worker.py` — "worker" with no subject; it emits the verdict corpus.
11. `oto/tools/verifiers/verify_ast_equivalence.py` vs `verify_method_equivalence.py` — two files indistinguishable without opening both; name the halves (`verify_symbols.py`, `verify_methods.py`).
12. `oto/tools/all_runs.py` — squashed pre-refactor script name; `oto stats` maps to it.
13. `oto/harness/tensile_probe.py` — "oracle" is repo jargon for "ask Tensile itself"; every sibling verb is "probe" (`checks/tensile_build_probe.py`).
14. `oto/harness/occupancy_bounds.py` — "audit" promises a judgment; the file computes three physical bounds (`occupancy_bounds.py`).
15. `oto/metrics/report_build.py` — sits in the acceptance-report namespace but builds the *status* report; `build_status.py` dissolves the ambiguity.
16. `oto/metrics/policy.py` — a catch-all name for the per-cell run/retire policy; `cell_policy.py`.
17. `oto/runners/corpus_loaders.py` — promises analytics; delivers the driver's whole-corpus ingestion + retirement sweep (`corpus_loaders.py`).
18. `oto/agents/meta.py` — "meta" is a non-name; it is the orchestrator (`agents/orchestrator.py`). `oto/agents/harness_tools.py` (echoes `oto/harness/`) rides along in the same class.
19. `oto/tensile/library.py` vs `oto/tensile/shipped_library.py` — inverted pair: the manifest cache vs the binary .dat; newcomers swap them every time.
20. `oto/tensile/synthesis/donor_mutator.py` (+ `db_knobs.py`, `db_patterns.py`) — "db" = "the analysis kernel_db.json" is insider vocabulary; "donor" is the files' own word for the same things.

Honourable mentions (kept, with notes): `oto/yamlio.py`, `oto/runners/auto.py`,
`oto/metrics/read_thermals.py`, `oto/metrics/analytics.py` ("Stage 5"), `oto/tools/consolidate_*`
(vague "consolidate" family prefix, §1.12), `oto/metrics/render_status.py` vs
`oto/metrics/run_status.py` (fine), `oto/runners/reporting.py`, `oto/checks/candidates.py`,
`oto/checks/db.py`, `oto/tensile/library_parity.py` (fine), `oto/tools/verify_run.py` (namespace
clash with `tools/verifiers/`).
