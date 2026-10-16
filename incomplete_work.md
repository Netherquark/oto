# Incomplete Work register (re-verified 2026-09-13; refreshed 2026-09-26)

Status key: RESOLVED (mechanism landed + proven) / PENDING (real gap, still open) /
PARTIAL (mechanism landed; execution/validation outstanding).

## 5.4 The equivalence verifiers were red on arrival — now all five pass

`python3 verify_all.py` reported **5 of 5 checks failing**. It was not caused by
the work in progress: a clean `HEAD` worktree with none of it failed identically.
The suite had simply been left red, which is the same failure mode as a guard that
is red before you touch anything — nobody reads it, so it stops being evidence.

Each failure had a different cause, and only one was a defect in the code rather
than in the check:

| check | cause | resolution |
|---|---|---|
| `ast equivalence` | four symbols decomposed in the AC-1b pass were never added to `RESTRUCTURED` | registered, after proving the call graph: for `mutate_and_feed` the transitive `self.*` reach set from HEAD is a strict **superset** of the base commit's — nothing lost. The check must walk mixin bases, or the four coverage methods look dropped when they moved intact to `oto/ledger/agent_coverage.py` |
| `gate differential` | **two real defects** (below), plus one deliberate message reword | fixed; see below |
| `config writer` | the writer now **forwards 9 knobs it used to silently drop** (`MaxOccupancy`, `AggressivePerfMode`, `UseSgprForGRO`, `InnerUnroll`, `FractionalLoad`, `NonTemporalA/B`, `NumLoadsCoalescedB`, `AssertFree1ElementMultiple`) and now honours `LocalSplitU` instead of discarding it. 190 of 5757 written configs differ | registered, with the acceptance requiring the diff to be **additions only** — a single removal still fails |
| `method equivalence` | `run_auto`, `run_phases`, `_compute_ab_verdicts` decomposed without registration | registered |
| `report html` | one section is indented differently in the source; the rendered DOM is identical | the check now strips pretty-printing line breaks before comparing, and still fails on any real content change (asserted) |

A sixth defect was in the harness itself rather than in any check:
`verify_all.py` did `ENV.setdefault("TENSILE_ROOT", "")`, which is not a no-op.
With the variable absent from the shell it **injected an empty value**, and
`require_tensile_root` reads "set but empty" as an error rather than falling back
to the repo-root `.env`. The report check therefore died on the harness's own
placeholder while passing when run directly — a difference of exactly the kind
that teaches people to ignore a guard. It now passes the environment through
unchanged.

**The two real defects the gate differential found:**

1. **Three copies of `parse_tensile_shape` had drifted.** The one in
   `oto/tensile/candidate.py` was a hand-rolled reparse that dropped the `_B16`
   batch suffix and replaced the original's regex digit-extraction with
   `str.split("x")` — so it raised `ValueError` where the original returned the
   default cube. No production module called it, but **both** failing verifiers
   imported it, so it had quietly become the thing they compared the original
   against. It now delegates to `oto/tensile.config_writer`'s copy, which is
   byte-identical to the base commit's.
2. **The gates raised instead of returning a verdict.** `int(config.get(k, D))`
   raises `TypeError` when a knob is present with a `None` value, in six places
   across the loads and assembly gates. A raising gate is exactly the opaque
   mid-run failure the gates exist to prevent. Fixed with `vgpr_model.knob_int`,
   which is provably identical to `int()` on every value `int()` accepts and only
   differs where `int()` would raise. The differential now buckets "the old gate
   raised where the new one returns a verdict" as its own category — **1593**
   comparisons — because counting it as either a regression or a pass hid it both
   ways.

The five root `verify_*.py` wrappers were also dead: each imported a `main` that
does not exist, because the moved verifiers are scripts, not libraries.
`verify_all.py` invokes them by path and never came through the wrappers, which
is why that stayed broken unnoticed. They now `runpy` the module.

## 5.3 CC:256 `AssertFree0/1ElementMultiple=4` — the empirical half is unverified

**Status: CPU-side gate landed; the GPU-side proof is a TTY task.**

The CC:256 steal batch (`candidate_rows.PLAN_BATCH`, R8) carries four rows with
`AssertFree0ElementMultiple=4` / `AssertFree1ElementMultiple=4`, on the theory
that the assertion unlocks `UseSgprForGRO` (VGPR relief for address
calculation) — Tensile's own recommended value for single precision.

**What is proven.** The rows hold on every shape they are offered across. `SS`
targets include **1365**, which is divisible by neither 2 nor 4, so an AF=4 row on
that family would be silently wrong; the new guard in
`candidate_pool._shapes_satisfying_assertions` filters such a row's shape list
rather than dropping it, and drops the row only when no shape survives.
`tests/test_element_assertions.py` locks the dimension mapping (AF0->M,
AF1->N, ASEM->K), the `ASEM % GlobalSplitU` rule, and the shipped rows.
`generate_candidates --dry-run` is unchanged at 381 candidates (+14 CC) and the
guard drops nothing today.

**Why the gate was necessary at all.** Tensile does not enforce this. Its own
`validParameters` comment says the kernel generator "will assume that the ...
size is some multiple", and for the summation case says it "requires runtime
checking to ensure the specified summation value meets the requirements" — which
Tensile does not do. The only divisibility it checks is
`AF0EM % GlobalLoadVectorWidthA == 0` (`GuaranteeNoPartialA`), a knob-to-knob rule
that says nothing about the problem size. The gate families in
`oto.tensile.gates` cannot help either: they validate a config and never see a
shape.

**What remains — needs the GPU, so run it in the TTY.** The gate proves the
assertion is *coherent*; it cannot prove the emitted kernel is *correct*. Before
trusting the first AF=4 row's GFLOPS, compare its output against a reference
GEMM on real silicon:

```bash
# 1. the first AF=4 CC:256 row (four exist; they differ only in LdsPad)
python3 -m oto.harness.generate_candidates --dry-run          # confirm the rows emit
# 2. run the CC:256 cell with correctness checking on, in the TTY
python3 port_tensile.py --auto --budget 1 --yes
```

Then compare the AF=4 row's result tensor against a reference CGEMM for
`256x256x256` complex single. **Until that comparison passes, treat the AF=4
rows' timings as unverified** — a wrong assertion does not produce a slow kernel,
it produces a fast wrong one. If it fails, the fix is the AF value, not the
measurement.

## 5.2 DONE (2026-10-16) — `GlobalSplitU` domain is now family-aware

`python3 -m oto.tools.deck_review legality` classified every
`(family, knob, value)` draw against the launch gates and found one real defect:
**`GlobalSplitU` offered `(1, 2, 4)` to all seven families, but `>1` can never run
on five of them.**

**The two restrictions are different, and conflating them is the trap.**

* **Structural** — Tensile allows `GlobalSplitU > 1` only for single, 8-bit float,
  double-with-BufferStore, Assembly-with-half-accumulate, `_GlobalAccumulation`,
  or MFMA (SolutionStructs:3553). gfx90c has no MFMA, so **CC and ZZ** (complex)
  and **HH_HPA / HS_HPA** (half in, f32 accumulate) can never run it. No companion
  knob rescues these.
* **Deck state** — **HH** is hardware-legal but banned *by decision*: `>1` on
  half Assembly additionally requires `AssertFree0ElementMultiple >= 2` for the
  atomics on edge tiles (SolutionStructs:3616), and the HH deck ships `AF0EM = 1`.
  So this one is a policy, and it lifts itself the day an HH candidate carries
  `AF0EM >= 2`.

`DD` keeps `(1, 2, 4)`: double plus BufferStore is a supported case, and the
census classes DD as *coupled* rather than refused.

**Fixed.** `FAMILY_KNOB_DOMAINS` now carries `"GlobalSplitU": (1,)` for CC, ZZ, HH,
HH_HPA and HS_HPA, and the census drops from 81 to 71 refused-standalone draws —
exactly the ten GSU values that could never run, and nothing else. The deck is
unchanged (381 candidates + 14 CC), because the generator gate-filtered these
anyway; what changed is that the mutator no longer spends a draw slot on them.

**The fix would have been cosmetic without the routing.** Three sites read the
base `FORWARD_KNOB_DOMAINS` directly and so bypassed the per-family override:
`db.synthesize_mutants`' narrow pass (the live one), and the four dead
`_xx_mutation_pattern` methods in `db_patterns`. A fourth site —
`candidate_pool._narrow_row_gen` — carried its own **hand-written tuple**
`("CC","ZZ","HH","HH_HPA","HS_HPA")`, a second home for the same fact that could
drift silently. All four now go through `forward_domain`, and the duplicated list
is gone. Routing the dead patterns also fixed a latent `KeyError`: they read
`FORWARD_KNOB_DOMAINS["GSU"]`, a key that does not exist.

**Locked by** `tests/test_db_mutator.py::test_gsu_above_one_is_never_offered_where_it_cannot_run`
and `::test_gsu_axis_survives_where_it_is_legal` — the second matters because a fix
that emptied SS's and DD's axis would pass the first while deleting the search
dimension the run depends on. A third test,
`::test_the_banned_gsu_test_is_not_vacuous`, exists because the narrow pass scores
every single-knob delta at priority 1.0, so a small `n` is filled by the first
knobs in dict order and never reaches `GlobalSplitU`: at `n=24` no mutant carries
it at all and the ban test passed without testing anything.

Everything else the census flags is **coupling, not defect** (`GLVW` must equal
`VectorWidth` or 1; `NLCA` must divide the load count; `StaggerU=0` needs
`StaggerUStride=0` drawn alongside). See `gfx90c_tuning_guide.md` §1.1.

## 6. DECISION REQUIRED — the LDS gate is calibrated to a value Tensile contradicts

**Owner: user. Do not change `LDS_BUDGET` or `BYTES_PER_ELEMENT["Z"]` until this
is decided.** Both are gate policy, and the second is load-bearing for the first.

`oto/tensile/gates/vgpr_model.py` computes an LDS proxy as
`(MacroTile0 + MacroTile1) * DepthU * bytesPerElement` and compares it against
`LDS_BUDGET = 16384`. Two facts, both measured from Tensile's own output:

1. **`BYTES_PER_ELEMENT["Z"]` is 8 but Tensile's complexDouble is 16 bytes.**
   Tensile/DataType.py:82 has `'reg': 4` and `numBytes() = numRegisters() * 4`
   = 16, and the same module's `FAMILY_BYTES_PER_ELEMENT` already says `"ZZ": 16`
   — the two tables in one file disagree.
2. **The budget was calibrated against the 8-byte value.**
   `tests/test_occupancy_gate.py::TestLdsGate::test_budget_sits_at_measured_boundary`
   asserts `(64+64)*16*bpe == 16384`, which holds only at `bpe = 8`. Measured from
   `amdhsa_group_segment_fixed_size`: Tensile emits **65536** for a ZZ 64x64x16
   (single-buffered 32768), so the current model understates the ZZ LDS footprint
   by 4× and overstates nothing. It therefore admits ZZ configs Tensile would
   refuse — the one direction the module docstring claims it cannot go.

The two are coupled: correcting (1) alone makes the gate reject **110 kernels
that Tensile built and ran** (worst: DD 64x64x32 and SS 128x128x32, both 32768
base / 65536 emitted; a Z 64x64x16 among them). Every one of those lands at
**4 waves/CU** — one resident workgroup — so the choice is not "widen or narrow",
it is "widen into a single-workgroup regime".

*Scope:* this is the **LDS-tile** byte width only. §8.1's "bytes per element for
the global load: C 8, Z 8" is a different quantity on a different path (the
`GLVW x bytes <= 16` register-vector cap), and both can be true at once; they
are not a contradiction and must not be "reconciled".

Existing values stay in place until decided. The corrected baseline would be
`"Z": 16` with `LDS_BUDGET = 32768` (preserving today's accept/reject boundary at
the true single-buffered footprint, which is what the `S`/`D` rows already match).
Reproduce with `python3 -m oto.harness.asm_occupancy --dtype Z --by gflops`.


## 4.14 In-Place Phases Fix & Telemetry v2 (RESOLVED — 2026-09-14)
- Fixed 48 invalid contraction entries in `phases.yaml` in-place (NLCA 3→1 ×46, DepthU 4→16 ×2; backup `archive/phases_20260914_prefix.yaml`).
- Replaced fragile telemetry sampler with `telemetry.py` (non-root sysfs, `mclk_hz` parsed correctly).
- Client/bench split PoC verified via `--prebuilt-client`.

**Gap (2026-09-26: CLOSED, now §4.15):** the frozen same-run pair (run_171325 =
0/11/0 parity) is superseded by the dedicated `gfx900_ref_*` reference floor;
verdicts are re-derived per workload cell vs the recalled floor chain
(ruler-adjusted, median-of-seeds, ±5% tie = parity).

## 4.15 Reference floor + per-cell A/B (RESOLVED — 2026-09-26; completion pending)

**Mechanism:** `tensile_library.py` parses the system ROCm gfx900 `TensileLibrary_*_gfx900.dat`
and pins 2,285 shipped kernels once at `gfx90c_results/gfx900_shipped_manifest.json`; every
report recalls the whole `gfx900_ref_*` chain (base + `--resume` continuations) via
`reference_chain` + `_compute_ab_verdicts`. `analytics.compute_native_vs_spoof_delta`
pairs by workload cell `(family, dtype, shape)` (`cell_key`) — best-of-cell median per
arm. The ±5% tie band originally used here is narrower than the corpus-measured
repeat noise (CV p90 27.8%, `ab_audit.repeat_dispersion`), so "parity" at ±5% does
not mean statistically indistinguishable; see `results.md` §12.3.

**the floor is 2,285 kernels, not 1,212.**
`gfx900_ref_20260925_152942` targeted 2,285 and was interrupted after 1,189
(1,073 completed / 116 failed); `gfx900_ref_20260926_201843_resume` targeted 1,212
of those and attempted every one. So the two runs between them attempted all
2,285. Any triage scoped to the resume deck alone would silently drop the 1,073
kernels the base run had already measured — every `tier_for` lookup is therefore
keyed by `tlib.phase_key()` (hash of the shipped solution name), and the resume
rebuild intersects against the manifest key set, not the loaded deck.
`phase_id` is *not* safe as an identity: 328 of 2,285 phase_ids change when the
deck is rebuilt after the config fixes, so pid-based triaging is unusable.

**Status:** the two runs now span the whole 2,285-kernel universe. Re-measurement
need is triaged in §4.16, and `--auto` gates tuning behind **T1 only**
(`_reference_remaining() == 0`).

**Residue/evidence:** `gfx90c_results/registry.db` 3,369 measured rows stamped
`cell_key`/`arm`/`kernel_key`; `idx_cell_key` index exists in the live registry
only — `registry.py` does not create it, so a fresh DB would miss it.

## 4.16 gfx900 floor triage: T1 active, T2 HELD (PARTIAL — T1 active, T2 pinned 2026-09-28)

**The problem.** Two independent defect classes made the shipped-kernel reference
floor untrustworthy. Both were ours, in the config *extraction*, not in Tensile:

1. **Incorrect config (127 kernels).** Our extractors mis-parsed the system
   `TensileLibrary_*_gfx900.dat`: the `VW` match was unanchored (so `VW1` leaked
   into `VectorWidth`), `TT4_2` was mis-parsed, and `GLVWA`/`GLVWB`/`GRVW` were
   never parsed at all. These phases ran with the *wrong shape*, so their
   numbers describe a computation we do not care about. Fixed in
   `tensile_library.py` (anchored `VW`, corrected `TT4_2`, full GLVW emission).
2. **Under-specified config (1,881 kernels).** `glvw`/`grvw` were left to
   Tensile's defaults rather than taken from the shipped solution name. The
   kernels are *correct*, just not pinned to what the vendor shipped, so the
   measurement is reproducible but not faithful to the intent. Also fixed in the
   parser — the rebuilt configs now pin all three values for all 2,285.

**Triage (`gfx90c_results/reference_rerun_manifest.json`, keyed by `phase_key`):**

| tier | n | behaviour | status |
|---|---|---|---|
| `T1_RERUN` | 127 | staged **first**, mandatory; `--auto` blocks until done | **ACTIVE** |
| `T2_RERUN_HELD` | 1,881 | not staged, does not block; opt-in only | **PENDING** |
| `T3_UNREPRODUCIBLE` | 277 | never staged, left failed | terminal |
| `T0_KEEP` | 0 | reuse the existing measurement | — |

127 + 1,881 + 277 = 2,285. T1's 127 = 64 Tensile rejections under the broken
config (rc=255, config-fixable) + 63 operator skips (rc=-1) that were therefore
never actually measured.

**T3 breakdown (277, terminal).** 154 half-input kernels pinned to `VW1` by
Tensile, 121 rejected by `assembly_class_valid()` (a real legality gap vs the
shipped `.dat`), 2 with no resolvable schedule. The vendored Tensile cannot
reproduce these; changing dtype or config to force them through would benchmark
a *different* computation, which is worse than a documented gap. Left failed.

**What is deliberately NOT in use (the pin).** T2's mechanism is fully landed
and tested — the shipped-config rebuild, the content fingerprint, the triaged
ordering, the hold/release switch — but the **staging decision is withheld**.
1,881 phases is ~1 day of GPU time to re-measure kernels that were never wrong,
for no correctness gain. The floor therefore keeps their existing
default-resolved measurements, and that is recorded rather than hidden.

Release when the floor is stable and a GLVW-faithful re-measurement is actually
wanted:

```bash
python port_tensile.py --gfx900-reference --release-under-specified
# or, via --auto:  python port_tensile.py --auto --release-under-specified
```

**Files:** `tensile_library.py` (`TIER_HELD`, `PINNED_TIERS`,
`apply_rerun_tiers(..., release_held=)`); `port_tensile.py`
(`run_gfx900_reference(..., release_held=)`, `run_auto(..., release_held=)`,
`--release-under-specified`); lists in `gfx90c_results/`:
`reference_rerun_first.txt` (127), `reference_rerun_last.txt` (1,881 held),
`reference_rerun_never.txt` (277); audit in
`reference_integrity_audit.json`.

**Verified (CPU-only, no GPU):** default deck stages **127** and nothing else;
`--release-under-specified` stages **2,008** with T1 first and T2 at the very
back; the `--auto` gate returns 127 owed → 0 once T1 completes, stays 0 with T2
untouched/partial/absent, and returns 27 with T1 at 100/127 — so held T2 can
never deadlock or falsely satisfy the floor. The real `--resume` path was
exercised with execution stubbed and reported `127 to run, 277 dropped, 1881
pinned as held`.

**To close:** run the 127 in a TTY, confirm the floor completes, then decide
whether T2 is worth its day. No code work is outstanding.

**2026-10-09 update — measurement-hygiene items that touch this tier land done:**
- kernel_db rebuilt with all runs folded (`harness/kernel_db.py --rebuild`): the
  locked-floor run contributes 14 019 kernel-shape rows; 19608 rows total.
- **Zero-contamination verified** on the rebuilt DB: 0 rows where the stored
  family disagrees with the kernel typecode (SB/DB/HB/CB/ZB → SS/DD/HH/CC/ZZ;
  HHS/HSS → HH); the `phase_auto_1_hh_*` rows that used to win SS:1024 at
  2142.55 are gone — honest SS:1024 is 1135.1. Root cause pinned and fixed in
  `analytics.py` (the `'auto'` FAMILY_TO_DTYPE entry) + `gfx90c_common.py`
  typecode resolvers (single source of truth), 28 unit tests
  (`tests/test_cell_attribution.py`).
- **Floor winner gate-legality proven** (`check_candidates.py --floor`): all 30
  per-cell floor winners pass all 4 legality gates natively; the 21 % whole-deck
  residue is generator-rule artifacts on non-winners plus 72 genuine
  occupancy-LDS entries (64-KB-LDS gfx900 kernels the APU's 16-KB-WG budget
  rejects — none ever won a cell).
- Real VGPR counts measured corpus-wide (`harness/measure_vgprs.py`) and the
  occupancy model's calibration is now measurement-ratified
  (`scheduler.MEASURED_VGPR_BY_DTYPE`).
- Full story: `gfx90c_tuning_guide.md`.

## 5.1 Refactor 1 (codebase organisation) — PARTIAL (2026-10-11)

Shipped: the flat root moved into an `oto/` package by responsibility, the three
gate families extracted from `scheduler.py` into `oto/tensile/gates/`, the
god-module (`port_tensile.py`, 3626 lines) split into
`oto/runners/{driver,benchmark,phases,reference,auto,reporting,analytics_loaders,
clocks,timing,synthesis,cli,toolchain,flags}` plus `oto/tensile/config_writer.py`,
and the remaining oversized modules split per the refactor's migration order
(the Refactor 1/2 planning MDs have been removed from the repo; see git history).

No behaviour change. Proven five ways against the pre-refactor commit
(`python3 plans/verify_all.py`):

* `verify_gate_differential.py` — 128,032 comparisons of every scheduler
  gate/function over an exhaustive config corpus, all equal.
* `verify_method_equivalence.py` — all 57 TensileDriver methods that moved into
  a mixin have an identical AST body.
* `verify_config_writer.py` — 6,037 live phases, old vs new config writer agree on
  (ok, reason) AND on the exact YAML bytes: 5,693 written, 344 refused, 0
  mismatches.
* `verify_report_html.py` — the rendered acceptance dashboard is byte-identical
  (99,287 bytes). This is the proof that the A/B delta arithmetic is unchanged.
* `verify_ast_equivalence.py` — every public symbol of every pre-split module
  still exists with the same body; 0 unexplained differences.

### DONE (2026-10-16) — functions still over 60 lines: 0 remaining

Acceptance criterion 2 of the plan ("no function over 60 lines") is now **met**.
All 31 offenders were decomposed without altering behaviour, proved per function
by the existing verifier suite (`python3 verify_all.py`) and the test suite, and
several by a differential check against the pre-refactor implementation (the
`regression_matrix` and `ab_audit` outputs are byte-identical over the repo's own
data).

**The rule is now executable.** `tests/test_function_length.py` asserts the
60-line span over `oto/**/*.py`, so a regression fails the suite instead of
silently re-accumulating. Three undefined-name regressions that the
decomposition introduced (and that the verifier suite did not catch, because
nothing constructed the affected objects) were found by pyflakes and fixed;
`_build_families` in `oto/tensile/library.py` had lost `scanned` from its
signature, which broke every `load_shipped_manifest` call.

**File-level criterion — the register's claim was stale and is corrected here.**
This section used to read "no file over 600 lines is met; the largest file is
`oto/tensile/legality.py` at 565 lines". The true maximum is
**`oto/checks/tensile_build.py` at 606 lines**, so the file criterion was already
violated before this round. It is deliberately **not** asserted by a test: a
guard that is red on arrival is ignored instead of obeyed. Fix the file, then add
the assertion. The function criterion is the one that matters and the one that is
enforced.

**Decision (2026-10-12, now implemented).** These cuts were deliberately *not*
implemented in the run-launch session (they churn the run loop immediately
before an overnight run). The `acceptance.py` criterion-1b check (total lines
`n.end_lineno - n.lineno + 1` over `oto/**/*.py`) was deleted with the other
untracked `plans/` scripts on 2026-10-14, which left the rule unenforced; it
now lives in `tests/test_function_length.py`, with the rationale above. The
**code-only** column in the table below identifies *which* seam was worth
cutting; it was never the exit test. The snapshot and closing plan are kept for
the record.

**Metric note (2026-10-12).** The rule only meant "a function too long to
follow", and several entries below were long because of their *docstring*, not
their code -- `reference_thresholds` was 78 lines of which 43 are code;
`load_phases_manifest` was 64 lines of which 32 are code. The table therefore
gives both the raw length and the **code-only** length (docstring, blank and
comment lines removed); the code-only column is the one that should drive the
work. 33 functions exceeded 60 *code* lines at that snapshot; all are now
decomposed.

Fixed this round, both mechanical data extractions proved equivalent:
`_init_db` (schema DDL moved to `_SCHEMA_DDL`/`_INDEX_DDL`/
`_EXPRESSION_INDEX_DDL`; the resulting `sqlite_master` is byte-identical) and
`write_report` (the 34-key per-cell verdict dict is now built from
`_VERDICT_FIELDS`; key set and order proven identical to the literal). Also
`oto/_map.py::main`, whose unreachable "package root" branch was deleted and the
recursive walk extracted to `_emit_tree` (README proven byte-identical).

Print the current list before starting (snapshot below; `code` drops the
docstring and comments):

```python
import ast
from pathlib import Path

def _code_lines(n, src):
    lines = src[n.lineno - 1:n.end_lineno]
    if (n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)):
        doc = n.body[0]
        for i in range(doc.lineno - 1, doc.end_lineno):
            if n.lineno - 1 <= i < n.end_lineno:
                lines[i - (n.lineno - 1)] = ""
    return sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))

for f in sorted(Path('oto').rglob('*.py')):
    src = f.read_text().splitlines()
    for n in ast.walk(ast.parse("\n".join(src))):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tot = n.end_lineno - n.lineno + 1
            if tot > 60:
                print(tot, _code_lines(n, src), f, n.lineno, n.name)
```

| # | function | location | tot | code | the seam to cut at |
|---|---|---|---|---|---|
| 1 | `mutate_and_feed` | oto/ledger/agent.py:250 | 227 | 141 | harvest -> filter -> emit |
| 2 | `run_auto` | oto/runners/auto.py:23 | 189 | 128 | floor-establish / tuning-loop / convergence |
| 3 | `iter_candidates` | oto/harness/candidate_pool.py:98 | 174 | 137 | wide / narrow / auto tiers |
| 4 | `run_phases` | oto/runners/phases.py:205 | 170 | 106 | skip/bypass policy vs the execution loop |
| 5 | `_load_ledger` | oto/metrics/run_status.py:113 | 163 | 111 | run-row read / chain resolve / record fold |
| 6 | `execute_phase` | oto/runners/benchmark.py:123 | 155 | 128 | record-pre / launch / record-post |
| 7 | `run_gfx900_reference` | oto/runners/reference.py:183 | 147 | 109 | run-dir swap vs delegation |
| 8 | `_compute_ab_verdicts` | oto/runners/reporting.py:124 | 140 | 109 | arm assembly / clock coverage / verdict build |
| 9 | `_run_tensile_benchmark` | oto/runners/benchmark.py:296 | 133 | 105 | argv+env / launch / poll / CSV collect |
| 10 | `_collect` | oto/metrics/ab_delta.py:45 | 131 | 82 | record fold vs per-cell statistics |
| 11 | `build_report` | oto/metrics/run_status.py:423 | 130 | 105 | report-dict assembly |
| 12 | `classify_outcome` | oto/ledger/mutator_outcomes.py:71 | 129 | 68 | outcome classification from on-disk CSVs |
| 13 | `generate_family_phases` | oto/tensile/candidate_emission.py:160 | 124 | 77 | phase-id build vs width-clamp retry |
| 14 | `probe_phase_config` | oto/checks/tensile_build.py:146 | 121 | 102 | Tensile solution vs kernel-writer |
| 15 | `build` | oto/harness/resolve_cells.py:182 | 119 | 106 | per-cell resolution table build |
| 16 | `phase_survey` | oto/harness/kernel_db.py:144 | 115 | 103 | DB survey |
| 17 | `build_matrix` | oto/harness/regression_matrix.py:85 | 110 | 96 | matrix build |
| 18 | `_resume_deck` | oto/runners/reference.py:28 | 109 | 65 | rebuild vs reuse vs triage |
| 19 | `audit` | oto/metrics/ab_audit.py:109 | 101 | 81 | classification vs certainty grading |
| 20 | `_pair_cells` | oto/metrics/ab_delta.py:247 | 101 | 75 | per-cell pairing (already partly cut) |
| 21 | `main` | oto/tools/allruns.py:192 | 99 | 89 | one handler per subcommand, as in cli.py |
| 22 | `main` | oto/checks/tensile_build.py:444 | 98 | 83 | one handler per subcommand |
| 23 | `converged` | oto/ledger/agent.py:151 | 98 | 75 | per-gate checks |
| 24 | `generate_acceptance_report` | oto/runners/reporting.py:264 | 98 | 66 | analytics vs timing vs verdicts |
| 25 | `render` | oto/metrics/render_status.py:219 | 93 | 86 | section renderers |
| 26 | `main` | oto/tools/verify_run.py:303 | 91 | 81 | one handler per subcommand |
| 27 | `append_candidates_batch` | oto/tensile/candidate_emission.py:65 | 88 | 64 | collide/dedupe/append |
| 28 | `synthesize_library` | oto/runners/synthesis.py:27 | 84 | 64 | emit / build / anti-alias / gate |
| 29 | `write_phase_config` | oto/tensile/config_writer.py:337 | 83 | 56 | gate / fork params / YAML dump |
| 30 | `main` | oto/harness/measure_vgprs.py:76 | 80 | 73 | one handler per subcommand |
| 31 | `mutate_winner` | oto/tensile/candidate.py:91 | 80 | 62 | 1-knob vs 2-knob neighbours |
| 32 | `__init__` | oto/runners/driver.py:136 | 80 | 60 | wiring vs run-dir setup |
| 33 | `_compute_family_coverage` | oto/metrics/report.py:121 | 80 | 51 | per-family vs by-size |
| 34 | `reference_thresholds` | oto/metrics/coverage.py:60 | 78 | 43 | band vs bars (docstring-dominated) |
| 35 | `_scan_dat_library` | oto/tensile/library.py:52 | 76 | 61 | scan vs assemble |
| 36 | `_offer` | oto/harness/candidate_pool.py:115 | 74 | 66 | one row per tier |
| 37 | `coverage_cells` | oto/metrics/coverage.py:172 | 74 | 57 | evidence vs state |
| 38 | `classify_cell_status` | oto/metrics/cell_status.py:28 | 74 | 50 | red vs orange vs graded |
| 39 | `_swizzle_feasible` | oto/tensile/gates/occupancy.py:323 | 73 | 48 | domain checks vs coupling |
| 40 | `select_deck` | oto/tools/consolidate_deck.py:206 | 70 | 49 | best vs sweep |
| 41 | `_family_matrix_rows` | oto/metrics/report_html.py:125 | 69 | 63 | family row vs size rows |
| 42 | `harvest` | oto/ledger/harvest.py:30 | 69 | 48 | score vs pick |
| 43 | `_reference_remaining` | oto/runners/reference.py:419 | 67 | 47 | universe vs newest-record scan |
| 44 | `load_phases_manifest` | oto/runners/phases.py:28 | 64 | 32 | deck vs overlay merge (docstring-dominated) |
| 45 | `load_benchmark_csv` | oto/metrics/analytics.py:231 | 63 | 49 | parse vs validate |
| 46 | `_fork_params` | oto/tensile/config_writer.py:177 | 63 | 42 | one block per knob family |
| 47 | `read_thermals` | oto/metrics/read_thermals.py:29 | 62 | 50 | read vs summarise |
| 48 | `_coverage_matrix_section` | oto/metrics/report_sections.py:227 | 61 | 58 | header vs body |
| 49 | `telemetry` | oto/tools/verify_run.py:170 | 61 | 49 | filter stages |

Approach per function: prefer the **code-only** column when choosing (a split
that only lowers the docstring count is not worth the churn); cut where a
sub-result first becomes available -- the same cut proved safe for the 13+
functions already decomposed this round -- extracting data literals into module
constants and cohesive steps into private helpers; then re-run the directly
affected tests plus `python3 plans/verify_all.py`, which is the guard that the
cut did not change behaviour.

#### Closing plan (proposed; implement after the overnight run)

**The rule that must actually pass.** AC 1b (the deleted `acceptance.py`
criterion):

```python
ln = n.end_lineno - n.lineno + 1        # TOTAL lines, docstring included
if ln > 60: ...                          # FAIL
```

over every `FunctionDef`/`AsyncFunctionDef` in `oto/**/*.py`. So the target is
**all 49 functions <= 60 total lines**. Do not lower a count by deleting a
docstring -- `docs/docstrings.md` is a separate, higher-priority requirement; a
docstring-heavy function (`reference_thresholds`, 78 total / 43 code;
`load_phases_manifest`, 64 / 32) is fixed by splitting its **code**, or, only
where there is genuinely no code seam, recorded as a justified exception.

**The extraction pattern** (the same one the 13 done cuts used):

1. Find the first point at which a self-contained sub-result exists
   (`harvest -> filter -> emit`, `argv+env -> launch -> poll -> collect`).
2. Move that block into a module-private function `_verb_noun(...)` that takes
   the locals it reads and returns the locals it produces; leave the public
   function as a sequence of named calls.
3. Where the block is a data literal (the way `_init_db -> _SCHEMA_DDL` and
   `write_report -> _VERDICT_FIELDS` were done), hoist it to a module constant
   and prove the emitted artifact byte-identical.
4. Never rename a public symbol or change a signature; private helpers may be
   named freely.

**Per-function plan** (`tot`/`code` from the scan above; risk = blast radius if
the cut is wrong).

| # | function | location | tot/code | risk | proposed extraction |
|---|---|---|---|---|---|
| 1 | `mutate_and_feed` | oto/ledger/agent.py:250 | 227/141 | HIGH | `_filter_settled_cells` (settled/retired gate), `_sample_mutants` (DB -> manifest fallback), `_emit_mutant_phases` (template + sweep build) |
| 2 | `run_auto` | oto/runners/auto.py:23 | 189/128 | HIGH | `_establish_floor`, `_run_tuning_iteration`, `_converge` |
| 3 | `iter_candidates` | oto/harness/candidate_pool.py:98 | 174/137 | HIGH | lift nested `_offer` to module level; `_offer_wide`, `_offer_narrow`, `_offer_auto`, `_offer_probes` |
| 4 | `run_phases` | oto/runners/phases.py:205 | 170/106 | HIGH | `_phase_should_run`, `_phase_skip_reason`, `_execute_one_phase` |
| 5 | `_load_ledger` | oto/metrics/run_status.py:113 | 163/111 | MED | `_read_run_rows`, `_resolve_run_chain`, `_fold_ledger_records` |
| 6 | `execute_phase` | oto/runners/benchmark.py:123 | 155/128 | HIGH | `_record_phase_start`, `_launch_phase`, `_record_phase_result` |
| 7 | `run_gfx900_reference` | oto/runners/reference.py:183 | 147/109 | HIGH | `_swap_to_reference_dir`, `_delegate_reference_phase` |
| 8 | `_compute_ab_verdicts` | oto/runners/reporting.py:124 | 140/109 | HIGH | `_assemble_arms`, `_clock_coverage`, `_build_verdict` |
| 9 | `_run_tensile_benchmark` | oto/runners/benchmark.py:296 | 133/105 | HIGH | `_benchmark_argv_env`, `_launch_benchmark`, `_collect_benchmark_csvs` |
| 10 | `_collect` | oto/metrics/ab_delta.py:45 | 131/82 | MED | `_fold_records`, `_per_cell_statistics` |
| 11 | `build_report` | oto/metrics/run_status.py:423 | 130/105 | MED | `_run_row`, `_phase_rows`, `_cell_rows` (report-dict parts) |
| 12 | `classify_outcome` | oto/ledger/mutator_outcomes.py:71 | 129/68 | MED | `_read_outcome_csvs`, `_classify_from_stats` (PROMOTED: verifier skips) |
| 13 | `generate_family_phases` | oto/tensile/candidate_emission.py:160 | 124/77 | MED | `_phase_id_for`, `_clamp_width_retry` |
| 14 | `probe_phase_config` | oto/checks/tensile_build.py:146 | 121/102 | MED | `_tensile_solution_ok`, `_kernel_writer_ok` |
| 15 | `build` | oto/harness/resolve_cells.py:182 | 119/106 | MED | `_resolve_cell_row` (per-cell table build) |
| 16 | `phase_survey` | oto/harness/kernel_db.py:144 | 115/103 | MED | `_survey_family`, `_survey_cell` |
| 17 | `build_matrix` | oto/harness/regression_matrix.py:85 | 110/96 | MED | `_matrix_row`, `_matrix_footer` |
| 18 | `_resume_deck` | oto/runners/reference.py:28 | 109/65 | HIGH | `_deck_rows_done`, `_deck_rows_remaining` |
| 19 | `audit` | oto/metrics/ab_audit.py:109 | 101/81 | MED | `_audit_one_cell`, `_audit_summary` |
| 20 | `_pair_cells` | oto/metrics/ab_delta.py:247 | 101/75 | MED | `_pair_key`, `_pair_row` |
| 21 | `main` | oto/tools/allruns.py:192 | 99/89 | LOW | one `_cmd_<sub>` handler per subcommand |
| 22 | `main` | oto/checks/tensile_build.py:444 | 98/83 | LOW | `_cmd_build`, `_cmd_probe`, dispatch in `main` |
| 23 | `converged` | oto/ledger/agent.py:151 | 98/75 | MED | `_converged_coverage`, `_converged_telemetry`, `_converged_ledger` |
| 24 | `generate_acceptance_report` | oto/runners/reporting.py:264 | 98/66 | MED | `_acceptance_header`, `_acceptance_rows` |
| 25 | `render` | oto/metrics/render_status.py:219 | 93/86 | LOW | one `_render_<section>` per section |
| 26 | `main` | oto/tools/verify_run.py:303 | 91/81 | LOW | one `_cmd_<sub>` handler per subcommand |
| 27 | `append_candidates_batch` | oto/tensile/candidate_emission.py:65 | 88/64 | MED | `_batch_rows`, `_batch_comment` |
| 28 | `synthesize_library` | oto/runners/synthesis.py:27 | 84/64 | MED | `_manifest_phases`, `_library_phases` |
| 29 | `write_phase_config` | oto/tensile/config_writer.py:338 | 83/56 | MED | `_config_body`, `_config_problem_type` |
| 30 | `main` | oto/harness/measure_vgprs.py:76 | 80/73 | LOW | `_measure_one`, `_write_table` |
| 31 | `mutate_winner` | oto/tensile/candidate.py:91 | 80/62 | MED | `_mutation_plan`, `_apply_mutation` |
| 32 | `__init__` | oto/runners/driver.py:136 | 80/60 | MED | `_init_paths`, `_init_state` |
| 33 | `_compute_family_coverage` | oto/metrics/report.py:121 | 80/51 | LOW | `_family_rows`, `_family_totals` |
| 34 | `reference_thresholds` | oto/metrics/coverage.py:60 | 78/43 | LOW | split the table build into `_reference_table` (docstring-dominated; code seam is the table construction) |
| 35 | `_scan_dat_library` | oto/tensile/library.py:52 | 76/61 | LOW | `_iter_dat_files`, `_parse_dat_entry` |
| 36 | `_offer` | oto/harness/candidate_pool.py:115 | 74/66 | LOW | nested; becomes module-level `_offer(row, ...)` returning bool |
| 37 | `coverage_cells` | oto/metrics/coverage.py:172 | 74/57 | MED | `_cell_state_row`, `_coverage_rollup` |
| 38 | `classify_cell_status` | oto/metrics/cell_status.py:28 | 74/50 | LOW | `_status_from_deltas`, `_status_from_coverage` (PROMOTED) |
| 39 | `_swizzle_feasible` | oto/tensile/gates/occupancy.py:323 | 73/48 | LOW | `_swizzle_tiles`, `_swizzle_check` |
| 40 | `select_deck` | oto/tools/consolidate_deck.py:206 | 70/49 | LOW | `_deck_key`, `_deck_filter` |
| 41 | `_family_matrix_rows` | oto/metrics/report_html.py:125 | 69/63 | LOW | `_matrix_cell`, `_matrix_row` |
| 42 | `harvest` | oto/ledger/harvest.py:30 | 69/48 | LOW | `_harvest_winners`, `_harvest_configs` (PROMOTED) |
| 43 | `_reference_remaining` | oto/runners/reference.py:419 | 67/47 | LOW | `_remaining_rows`, `_remaining_shapes` |
| 44 | `load_phases_manifest` | oto/runners/phases.py:28 | 64/32 | LOW | `_manifest_rows`, `_manifest_validate` (docstring-dominated) |
| 45 | `load_benchmark_csv` | oto/metrics/analytics.py:231 | 63/49 | LOW | `_csv_columns`, `_csv_rows` |
| 46 | `_fork_params` | oto/tensile/config_writer.py:178 | 63/42 | LOW | `_fork_overrides`, `_fork_merge` |
| 47 | `read_thermals` | oto/metrics/read_thermals.py:29 | 62/50 | LOW | `_thermal_samples`, `_thermal_summary` |
| 48 | `_coverage_matrix_section` | oto/metrics/report_sections.py:227 | 61/58 | LOW | `_cov_header`, `_cov_rows` |
| 49 | `telemetry` | oto/tools/verify_run.py:170 | 61/49 | LOW | `_telemetry_stages` |

**Tooling that changes with the cuts.**

* `plans/verify_ast_equivalence.py` -- a body difference in a head module *not*
  in `DECOMPOSED` is a hard failure. Six head modules are not listed yet and
  each needs an entry (with the same "proved by ..." justification the list
  already carries) before its functions are cut:
  `agent.py` (`mutate_and_feed`, `converged`), `coverage.py`
  (`reference_thresholds`, `coverage_cells`), `check_tensile_build.py`
  (`probe_phase_config`, `main`), `harness/resolve_cells.py` (`build`),
  `allruns.py` (`main`), `verify_run.py` (`main`, `telemetry`).
  The other 43 functions are already safe: their head module is `DECOMPOSED`
  (`port_tensile.py`, `scheduler.py`, `analytics.py`, `report.py`,
  `run_status.py`, `ab_audit.py`, `consolidate.py`, `tensile_library.py`,
  `db_mutator.py`,
  `harness/{generate_candidates,kernel_db,measure_vgprs,regression_matrix}.py`)
  or the symbol is private / `PROMOTED` and therefore skipped (`_offer`,
  `_collect`, `_pair_cells`, `_family_matrix_rows`, `_scan_dat_library`,
  `_swizzle_feasible`, `_fork_params`, `_reference_remaining`,
  `_coverage_matrix_section`, and the `PROMOTED` `classify_outcome`, `harvest`,
  `classify_cell_status`, `generate_family_phases`, `append_candidates_batch`).
* `plans/acceptance.py` -- deleted 2026-10-14; 1b is register-enforced only. (If the team decides
  the **code-only** metric is the rule instead, change 1b to strip the docstring
  and the exit set drops to the 33 code-only entries -- make that call once,
  here.)

**Batch order** (each batch ends green).

1. **LOW -- pure shuffles, no run-loop path (23).** One handler per subcommand
   for `allruns.main`, `tensile_build.main`, `verify_run.main`+`telemetry`,
   `measure_vgprs.main` (mirror `runners/cli.py`); section renderers for
   `render`; plus `select_deck`, `reference_thresholds`,
   `_compute_family_coverage`, `coverage_cells`, `classify_cell_status`,
   `harvest`, `_family_matrix_rows`, `_coverage_matrix_section`,
   `load_phases_manifest`, `load_benchmark_csv`, `read_thermals`,
   `_reference_remaining`, `_fork_params`, `_swizzle_feasible`,
   `_scan_dat_library`.
2. **MED -- data assembly (18).** `_load_ledger`, `build_report`, `_collect`,
   `_pair_cells`, `audit`, `generate_family_phases`,
   `append_candidates_batch`, `synthesize_library`, `probe_phase_config`,
   `build`(resolve_cells), `phase_survey`, `build_matrix`, `write_phase_config`,
   `mutate_winner`, `driver.__init__`, `generate_acceptance_report`,
   `classify_outcome`, `converged`.
3. **HIGH -- the run loop last, one function per commit (9).**
   `mutate_and_feed`, `run_auto`, `iter_candidates`, `run_phases`,
   `execute_phase`, `_run_tensile_benchmark`, `run_gfx900_reference`,
   `_resume_deck`, `_compute_ab_verdicts`. These are plan §7's "subtle
   skip/reference-floor interaction"; cut `phases.py`/`reference.py` before
   `auto.py`, exactly as §7 orders it.

**Verification per cut** (the ritual that proved the 13 done cuts):

1. `python3 -m py_compile <file>` + `python3 -c "import oto.<mod>"`.
2. The directly-affected test module(s) (e.g. `tests/test_runner.py` for
   `run_auto`, `tests/test_agent*.py` for `agent.py`).
3. `python3 plans/verify_all.py` (add the head module to `DECOMPOSED` first).
4. Full suite once per batch: `TENSILE_ROOT=... pytest -q` (~6.5 min).
5. ~~`python3 plans/acceptance.py`~~ -- deleted; run the full suite instead.

**Exit criteria.** AC 1b passes; `verify_all.py` green; full suite green; every
new `DECOMPOSED` entry carries its one-line justification.

### PENDING — known slop observed during the move

* **`oto/checks/db.py`, `oto/checks/retirement.py`** — two throwaway ad-hoc
  sqlite scripts that used to execute at *import* time (no `main()` guard).
  Wrapped in `main()` this round so importing the package is side-effect free,
  but the bodies are still one linear script each; they are not real checks and
  should either become proper checks or be deleted.
* **`oto/tools/consolidate_deck.py:119`** — ~~its docstring still cites
  `scheduler.FAMILY_BYTES_PER_ELEMENT`~~ **FIXED 2026-10-12**: now cites
  `oto.tensile.gates.vgpr_model.FAMILY_BYTES_PER_ELEMENT`.
* **`oto/ledger/harvest.py:136`** — ~~a comment cites "scheduler family
  decks"~~ **FIXED 2026-10-12**: comment no longer names the deleted module (the
  attribute is `self.scheduler.family_decks`, itself logged below).
* **`oto/tensile/candidate.py:51`** — `_ = (depth_u, dtype_char, tile_dims,
  FAMILY_DTYPE_CHAR, NUM_CUS)` exists purely to keep linters quiet about
  re-exports. The `__all__` list already does that job; the throwaway tuple
  should go.
* **`oto/tensile/candidate.py` `parse_tensile_shape`** — a lazily-delegated
  re-export for the pre-split import surface. Its only caller is the test suite;
  once the tests import from `config_writer` it can be deleted.
* **`oto/harness/candidate_pool.py`** — `fingerprint_config` is imported but the
  module has its own `_fingerprint`; one of the two is dead.
* **duplicated dark-palette CSS** in `oto/metrics/report_css.py`
  (`DASHBOARD_CSS` declares the same 23 custom properties twice: once as
  `[data-theme="dark"]`, once inside `prefers-color-scheme`). Deliberate, and
  only because collapsing it changes which theme wins when an operator has
  explicitly pinned a light theme. If that precedence is ever worked out, this
  is the one place to do it.

### PENDING — slop observed during the docstring/finish pass (2026-10-12)

Case-by-case review register. Each item was observed while verifying the
Refactor 1 move; none changes behaviour, so none was fixed opportunistically.
Items 1–5 are genuine defects worth a decision; items 6–10 are hygiene.

1. **Hardcoded Tensile fallback paths contradict the toolchain contract.**
   `oto.runners.toolchain` states "There is deliberately no fallback" and raises
   when `TENSILE_ROOT` is unset. Four other modules instead fall back to the
   author's absolute checkout if the env var is missing:
   * `oto/checks/candidates.py:44`
   * `oto/tools/allruns.py:42`
   * `oto/tools/consolidate_deck.py:27`
   * `oto/tools/consolidate_floor.py:24`
   These are pre-refactor (the paths moved with the code), but they are the
   reason a fresh checkout silently reads a machine-specific path. Decide: route
   all four through `require_tensile_root()` or make the fallback explicit and
   documented.

2. **`oto/tools/consolidate_floor.py:24` `_TENSILE_ROOT` is dead.** It is
   defined and never read (the live reader is `oto/tools/consolidate_deck.py`).
   Delete the constant (and its hardcoded path) with item 1's fix.

3. **Swallowed exceptions in `oto/runners/reporting.py`.** Line ~101:
   `except Exception: return native_records, spoof_records` silently turns a
   registry read failure into "no arm data". Line ~359:
   `except Exception as e: print("Report generation error: …"); return None`
   prints and returns `None` instead of failing the report. A report that cannot
   be generated should be loud, not a `None`.

4. **Stray untracked data dirs under `oto/`.** `oto/tensile/gfx90c_results/`,
   `oto/metrics/gfx90c_results/` and `oto/metrics/gfx90c_runs/` were created by
   running a tool with a relative `base_dir` from inside the package. They are
   not tracked and not intended. `oto/_map.py` now skips a directory with no
   modules so they no longer pollute `oto/README.md`. **Removed 2026-10-12.**
   They are gitignored (`gfx90c_runs/`, `gfx90c_results`), so a future run of a
   tool from inside the package with a relative `base_dir` can recreate them --
   the real fix is to make those tools resolve `base_dir` against the repo root.

5. **Corpus counts in docstrings — swept 2026-10-12.** The convention forbids
   them, so every one found was replaced with a date-and-decision phrasing or a
   qualitative claim: `oto/__init__.py` ("~40 importers"),
   `oto/metrics/ab_audit.py` + `oto/metrics/ab_records.py` ("~94% auto" and two
   run ids), `oto/metrics/ab_band.py` ("36% CV / 65% CV"), `oto/metrics/report.py`
   ("~1%"), `oto/harness/candidate_rows.py` ("2026-10-09 batch"),
   `oto/metrics/run_plan.py` ("111 phases"), `oto/runners/reference.py` and
   `oto/tensile/library.py` ("1073 of 1212"), `oto/tensile/config_writer.py`
   ("121 phases"), `oto/tensile/gates/occupancy.py` ("167/167"),
   `oto/tensile/legality.py` ("116 … 90 false"), `oto/tools/consolidate_floor.py`
   ("17 of 38 cells", "11.9%"). Hardware constants (64 KB, `65536/2`) and
   Tensile `file:line` citations were kept — the convention allows both.

6. **Duplicate/shadowed definitions (pyflakes "redefinition of unused").**
   * `oto/metrics/ab_audit.py:45` re-defines `phase_family` and `:85`
     re-defines `measured_band`, both imported at `:31`/`:27`. One of the two is
     dead; the local def wins.
   * `oto/metrics/analytics.py:50` re-defines `FAMILY_TO_DTYPE` imported at
     `:34`.
   * `oto/runners/auto.py:44` re-defines `DEFAULT_ITERATIONS`/`DEFAULT_MUTATIONS`
     imported from `oto.runners.auto_prompt`.
   * `oto/ledger/mutator.py:47` imports `TEMPLATE_KEYS` twice.

7. **Module-level `import yaml` shadowed by a function-local `import yaml`.**
   `oto/ledger/mutator.py` (`:423`, `:446`), `oto/harness/candidate_overlay.py`
   (`:74`, `:119`), `oto/harness/candidate_pool.py` (`:70`),
   `oto/metrics/analytics.py` (`:107`). The module-level import is then unused.

8. **Dead locals.** `oto/tensile/synthesis/db_patterns.py:65` (`patterns`),
   `oto/checks/tensile_build.py:159` (`gp`) and `:468` (`model`),
   `oto/metrics/ab_audit.py:119` (`cross`), `oto/runners/auto.py:167`
   (`results`), `oto/runners/reference.py:225` (`deck`).

9. **~190 unused imports across `oto/`.** Mostly the union of a moved module's
   import header landing in each split child, plus pre-existing debt (the
   pre-refactor tree had 25). pyflakes is clean on *undefined names*; this is the
   "imported but unused" tail. Not fixed wholesale because removing a
   side-effect import is exactly the case-by-case call this register exists for.

10. **`self.scheduler` is a legacy shim name.** The attribute holds a
    `CandidateGenerator` (`oto/runners/driver.py:167`), and is read as
    `self.scheduler.family_decks` / `.mutate_winner` / `.emit_candidate` across
    `oto/ledger/{agent,harvest}.py`, `oto/runners/{auto,synthesis}.py`. Renaming
    it to `self.generator` is mechanical but touches many call sites.

11. **`oto/ledger/registry_core.py` carries two refactor artifacts.** (a) A dead
    second module-docstring string literal (the old `registry_sqlite.py` header,
    lines ~15-20) left behind by the docstring-merge; only the first string is a
    docstring, the second is a no-op expression. (b) An empty `class
    SQLiteRegistry:` stub with only a one-line docstring, shadowed by the real
    composition root in `oto/ledger/registry.py`. Baseline had exactly one
    docstring and one class; these are split leftovers. Harmless, confusing,
    delete on the next touch.

12. **`oto/tensile/synthesis/db_patterns.py` carries four dead mutators.**
    `_ss/_dd/_cc/_zz_mutation_pattern` were restored byte-identical to baseline
    after the split truncated them; they are dead in baseline too
    (`synthesize_mutants` uses only `_forward_draws`/`_floor_direction`).
    `_ss_mutation_pattern` additionally reads `FORWARD_KNOB_DOMAINS["GSU"]`, a key
    that does not exist -- a latent `KeyError` if it is ever called. Decide:
    delete, or wire up with the missing key.

13. **`oto/runners/benchmark.py::_write_phase_config` is a delegating shim.**
    A one-line method forwarding to
    `oto.tensile.config_writer.write_phase_config`, restored because
    `oto/checks/tensile_build.py` and a test call `driver._write_phase_config`.
    Keep it as the driver's surface, or redirect the two callers to the module
    function and drop the method.

14. **`oto/_map.py::main` root branch was dead.** `PACKAGES` has no empty entry
    and the `oto/` root holds only `__init__.py`/`_map.py` (both in `SKIP`), so
    the "package root" branch could never run. Removed this round and the
    recursive walk extracted to `_emit_tree`; `oto/README.md` regenerates
    byte-identically.

**Fixed this round while finishing Refactor 1** (recorded so the register is
honest): the two stacked-module-docstring SyntaxErrors (17 files via the since-deleted
`plans/merge_docstrings.py`, plus `oto/device/peaks.py` by hand, which also
gained its missing `typing` import and lost a shadowed `import re`); the
`oto.tools.consolidate` re-export façade (`_fam`, `_is_legal`, `dtype_bytes`,
`target_cells`, `_TENSILE_ROOT`) that two test modules import;
`oto/harness/occupancy_audit.py` importing VGPR constants from
`oto.tensile.candidate` instead of `oto.tensile.gates.vgpr_model`; and the
`oto/tools/consolidate_install.py` duplicated CLI/constants block.

**Regression fixes this round (2026-10-12).** Four real losses introduced by the
move were found and repaired against baseline `2824c2f`, each proved by an
independent baseline-vs-HEAD symbol comparison and the suite:
* the public gate name `ldspad_feasible` had been renamed to `..._defasible`
  repo-wide (tests and verifiers were adapted to the typo); restored.
* the four `_*_mutation_pattern` methods (item 12) had been truncated/lost;
  restored.
* `TensileDriver._write_phase_config` had been lost to the extraction, so
  `oto/checks/tensile_build.py` and a test silently no-op'd; the delegating
  method (item 13) was restored.
* `oto/tensile/synthesis/tile_space.py` was added to own the shared tile/group
  vocabulary (`TILE_KNOBS`, `ALL_GROUPS`, `TEMPLATE_KEYS`, `reconcile_tile`,
  `tile_product_holds`) that `manifest.py` and `db*.py` had each been defining.

**Docstring corrections this round (2026-10-12).** False `Public API:` claims
fixed: `oto/harness/candidate_rows.py` named non-existent `AUTO_ROWS`/
`BEAT_THE_SPOOF_ROWS` (the real names are `AUTO_EXPLICIT`/`PLAN_BATCH`);
`oto/tensile/library_parity.py` listed a `main` that lives in
`oto.checks.library_parity`; `oto/tools/consolidate_floor.py` listed `LIVE_DB`,
which lives in `oto.tools.consolidate_targets`; `oto/runners/clocks.py` listed
class constants as module-level names; `oto/tensile/synthesis/__init__.py` said
"the four modules"; and `oto/_map.py` lacked the convention block.

**`plans/verify_ast_equivalence.py` hardened (2026-10-12).** The private-symbol
skip let a deleted helper pass silently (it hid the `db_patterns` loss). The
verifier now asserts every `PROMOTED` entry still exists under its new name
(`FOLDED` helpers excepted, proved by `verify_gate_differential.py`).

### NOT ATTEMPTED (deliberate)

* `oto/device/profile.py` and `oto/device/profile_registry.py` were **not**
  created. The plan marks them as the Refactor 2 seam; creating stubs now would
  be scaffolding with no caller.
* `harness/` moved to `oto/harness/`, but `tests/` stays at the repo root —
  the plan says tests move last.
