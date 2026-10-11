# Refactor 1 — Codebase Organisation Proposal

**Status: PROPOSAL (planning only, no code written).** Companion to
`REFACTOR_2_UNIVERSAL_GPU.md`. This refactor is **device-agnostic** — it can be
executed on the current gfx90c tree as-is, and Refactor 2 then layers the
device-profile seam on top without re-doing it.

**The problem, stated plainly.** The codebase works but it is not legible, and it
is not legible in a way that is expensive to change:

| file | lines | the problem |
|---|---|---|
| `port_tensile.py` | **3617** | The monster. Runner + gates + config-writing + reference-floor + A/B + reporting + CLI all in one module. A change to the skip logic requires understanding the reference-floor resume. |
| `scheduler.py` | 1468 | Candidate generation + three gate families + the VGPR model + deck precedence. The gates are interleaved with the candidate sampler. |
| `report.py` | 1337 | Every report format in one place. |
| `run_status.py` | 1062 | Cost model + plan pricing + telemetry reconciliation. |
| `registry.py` | 855 | Ledger + proposals + observations + coverage view + durability. |
| `analytics.py` | 930 | CSV loading + per-cell aggregation + LCB + dtype attribution. |
| `ab_audit.py` | 721 | A/B verdict logic. |
| `tensile_library.py` | 667 | Kernel-name parsing + shipped-manifest loading. |
| `mutator.py` / `agent.py` | 628 / 626 | Ledger mutation + convergence loop; two halves of one state machine split across files with a re-entrant construction path. |
| `legality.py` | 561 | The legality prior. |
| `check_tensile_build.py` | 556 | Build-result scraping. |
| `consolidate.py` | 764 | Deck consolidation. |
| `synthesis.py` / `db_mutator.py` | 395 / 393 | Two synthesizers (manifest + DB-hooked) that duplicate the group/tile vocabulary. |
| 19 more `.py` | … | Various. |

Two structural sins repeat throughout:

1. **God modules.** `port_tensile.py` alone violates the single-responsibility
   principle a dozen times over; `_write_phase_config` is a ~240-line method that
   parses shapes, maps patterns, gates, and writes Tensile YAML.
2. **Inconsistent inline docs.** Some functions have excellent docstrings
   (the occupancy gate, `classify_outcome`); others are bare. There is no
   project-wide convention for what a module docstring must contain, so a reader
   cannot tell where a responsibility starts or ends without reading the body.

A third, quieter cost: **the gfx90c gates are woven into the generic modules**
(`scheduler.py`, `port_tensile.py`). That is Refactor 2's subject, but it is also
an organisation problem — the gates are a *policy layer* over the candidate
generator, and they currently live *inside* it.

---

## 1. Goals

- **No file over ~600 lines** (with a hard exception process for genuinely
  cohesive tables), and **no method over ~60 lines**.
- **One responsibility per module**, named for that responsibility.
- **A documented convention** for module and function docstrings, applied
  uniformly. This convention should be properly integrated into the docs ecosystem. start by going through @claude.md
- **The gate policy extracted** from the candidate generator (prepares Refactor 2).
- **No behaviour change.** This is a pure re-organisation; the 675-test suite
  must stay green at every step. No regressions of any kind whether test measured or obvious shortcomings that current tests might not account for.

## 2. Target layout

Move the flat root into an `oto/` package with submodules by responsibility, and
keep the thin CLI/driver scripts at the root:

```
oto/
  __init__.py            # public API re-exports, __version__
  device/
    profile.py           # (Refactor 2 seam) DeviceProfile dataclass + loader
    profile_registry.py  # codename -> profile resolution
  tensile/
    library.py           # tensile_library.py  (kernel-name parsing, manifest)
    candidate.py         # scheduler.CandidateGenerator (sampler + deck)
    config_writer.py     # _write_phase_config + shape/pattern parsing
    gates/
      __init__.py
      assembly.py        # assembly_class_valid + the GSU/complex/half rules
      occupancy.py       # occupancy_feasible, ldspad_feasible, swizzle, VGPR model
      loads.py           # _validate_tensile_loads (NLCA/GLVW/divisibility)
      vgpr_model.py      # MEASURED_VGPR, FAMILY_BYTES_PER_ELEMENT, budgets
    legality.py          # the manifest-derived legal prior
    synthesis/
      __init__.py
      manifest.py        # synthesis.py (coverage-guided manifest draws)
      db.py              # db_mutator.py (DB-hooked wide+narrow+direction)
      tile_space.py      # shared tile/group vocabulary + reconciliation
  ledger/
    registry.py          # SQLite registry (records/runs/phases/proposals)
    mutator.py           # Mutator (ledger-backed mutation + outcome)
    agent.py             # ConvergenceAgent (harvest -> mutate -> loop)
  metrics/
    analytics.py         # CSV loading + per-cell aggregation + LCB
    ab_audit.py          # A/B verdicts
    report.py            # all report formats
    run_status.py        # cost model + pricing
    coverage.py          # coverage view + states
  runners/
    auto.py              # the --auto convergence loop (port_tensile's run_auto)
    reference.py         # gfx900 reference-floor recall/resume
    phases.py            # run_phases + the identical-fp skip + per-phase bypass
    cli.py               # argparse + stage dispatch (the port_tensile main)
  checks/
    check_candidates.py  # check_candidates.py
    check_tensile_build.py
    check_library_parity.py
    ... (the check_* family)
  harness/               # (already a package) the analysis harness
```

Root keeps only: `command.txt`, the `.md` docs, and thin `*_cli.py` entrypoints
(if any) that import from `oto`.

## 3. Migration steps (each independently testable)

The order is by dependency: extract leaves first, the god-module last. After
each step the full suite must pass.

1. **`tensile_library.py` -> `oto/tensile/library.py`.** Pure move + import
   update. No internal change. (Lone leaf; 667 lines is fine.)
2. **Extract the VGPR/occupancy model** (`FAMILY_BYTES_PER_ELEMENT`,
   `MEASURED_VGPR`, `LDS_BUDGET`, `VGPR_BUDGET`, `occupancy_feasible`,
   `ldspad_feasible`, the swizzle rules) from `scheduler.py` into
   `oto/tense/…/gates/occupancy.py` + `vgpr_model.py`. `scheduler.py` imports
   them. The gates stop being methods interleaved with the sampler.
3. **Extract `assembly_class_valid`** into `oto/tensile/gates/assembly.py`.
4. **Extract `_validate_tensile_loads`** into `oto/tensile/gates/loads.py`.
   `scheduler.validate_config` becomes a thin orchestrator over the three gate
   modules.
5. **Split `port_tensile.py`** (the big one), in this order:
   a. `_write_phase_config` + shape/pattern parsing -> `oto/tensile/config_writer.py`.
   b. the identical-fp skip + per-phase bypass + `run_phases` -> `oto/runners/phases.py`.
   c. the gfx900 reference-floor recall/resume -> `oto/runners/reference.py`.
   d. the `--auto` loop -> `oto/runners/auto.py`.
   e. argparse + stage dispatch -> `oto/runners/cli.py`.
   Each extraction updates `port_tensile.py` to import from the new module; the
   3617-line file shrinks to a facade that `oto.runners.cli` calls.
6. **Split `report.py`, `run_status.py`, `registry.py`, `analytics.py`,
   `ab_audit.py`** into the `oto/metrics/` + `oto/ledger/` modules above. These
   are cohesive; the split is mostly moving code and fixing imports.
7. **Unify the two synthesizers.** `synthesis.py` (manifest) and `db_mutator.py`
   (DB-hooked) both define tile/group vocabulary and forward-knob domains.
   Extract the shared tile/group vocabulary + tile reconciliation into
   `oto/tensile/synthesis/tile_space.py`; both synthesizers import it.
8. **Docstring convention.** Define it once (see §4) and apply it file-by-file
   in the same commits as the moves, so a move and its doc update never land
   separately.

## 4. The docstring convention

Every module gets a docstring with: **what it owns**, **what it deliberately
does not own** (the one-fact-one-home rule, applied to code), and **the public
function/class names a caller needs**. Every public function gets: a one-line
summary, `Args`/`Returns`, and — where the behaviour is non-obvious — a
`Why` line citing the file:line of the source fact (the codebase already does
this well in places; the convention is to do it everywhere).

Example header for `oto/tensile/gates/occupancy.py`:

```python
"""Register-file and LDS occupancy gates.

Owns: the CPU-only model that reproduces every observed gfx90c occupancy
outcome (occupancy_feasible, ldspad_feasible, the swizzle StaggerU rules).
Does NOT own: the candidate generator (oto.tensile.candidate), the VGPR
*measurement* table (oto.tensile.gates.vgpr_model), or any device constant
(oto.device.profile — Refactor 2).
"""
```

## 5. Constraints and non-goals

- **No behaviour change.** Pure re-organisation. The 675-test suite is the
  guard; it stays green at every step.
- **No device-generalisation here.** Moving a gfx900 reference or a gfx90c
  constant is Refactor 2's job. Refactor 1 only moves code.
- **Do not rename public APIs yet.** `scheduler.CandidateGenerator`,
  `mutator.Mutator`, `agent.ConvergenceAgent`, etc. keep their names and are
  re-exported from `oto/__init__.py` so the ~40 importers keep working during
  the transition.
- **The `harness/` and `tests/` trees move last**, after the `oto/` package is
  stable, because they import the root modules most aggressively.

## 6. Acceptance criteria

1. No `.py` file over 600 lines (excluding data tables); no function over 60.
2. Every module docstring states owns / does-not-own / public API.
3. The three gate families live in `oto/tensile/gates/` and are imported by,
   not interleaved with, the candidate generator.
4. `port_tensile.py` is under ~400 lines and contains only the facade + CLI.
5. The full test suite passes unchanged after every step.
6. `grep -rn "gfx90c" oto/` shows the device constants appearing only in
   `oto/device/` (the Refactor 2 seam) — i.e. the extraction did not scatter
   new device copies.

## 7. Effort and risk

- Steps 1-2, 4, 7 are mechanical (move + fix imports + docs). Low risk.
- Steps 3, 5, 6 require care (the god-module's responsibilities are entangled),
  but the test suite is the guard. Budget the most time for 5a (the config
  writer) and 5d (the auto loop).
- **Risk:** the `port_tensile.py` skip/reference-floor interaction (the seed
  fallback at the bypass, the ledger-gated bypass) is subtle. Mitigation:
   extract `phases.py` and `reference.py` with their tests first, before
   touching `auto.py`.

programmatically verify that all of your work was solid, that there are no regressions, that all of the acceptance criteria are met, that there's good documentation throughout. dont stop until you've done a perfect fucking job you piece of shit. and wherever you observe spaghetti / slop / inefficient / gimicky / shim / patched terrible code mark it in incomplete work for a refactor i will later on look into this case by case. 
work as hard as possible and crosscheck your work to ensure no mistakes take as much time as you need but do this refactor right in one shot and verify that the entire flow is intact once done.

the docs ecosystem should clearly differentiate itself from the docstrings, docstrings are module / function / file specific documentation to improve maintainability / readability, the docs ecosystem should be clearly delineated with a boundary as higher level context for agents to effectively work on the codebase, docs ecosystem shouldnt be polluted with trivial / niche specifics so case by case one by one propose paragraph by paragraph which parts should be whittled down / removed / moved to docstrings be very careful with the docs ecosystem its crucial to this entire project.