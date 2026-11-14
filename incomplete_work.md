# Incomplete Work register (consolidated 2026-11-14)

The 1,007-line archived register was consolidated and deleted; its
contents were folded into the docs ecosystem the same day (GPU/LDS
validation doc `gfx90c_theoretical_limits.md` §6.1, floor triage in
`results.md` §8–§9, GSU/domain notes in `gfx90c_tuning_guide.md`, the
verifier-bringup history in `changelog.md`). The git object holds the
pre-fold snapshot; recovered in any case. Only the *open* items are kept
live here; completed work lives in `changelog.md`, decisions in `docs/`.

## Open items

- **C4 — gfx902 starter research** (agent-1 candidate census + agent-2
  per-class research report). Blocked on the owner's API key.
  (`docs/gfx902_starter.md` has the public identity + open questions; the
  research prompt only runs once the key exists.)
- **C7.1 — gfx902 starter profile** (`profiles/gfx902.json`). Blocked on C4:
  a human must review the numbers and accept the profile; testing it blind
  would pretend gfx902 hardware exists, which it does not here. The gate
  tests already exercise a `dataclasses.replace`-derived synthetic device.
- **CC:256 `AssertFree0/1ElementMultiple=4` — legality verified 2026-11-14
  on silicon; perf run not done (TTY-only).** All 11 probes (the CC 256/512
  AF0/1EM=4 config, its AF0/1EM=2 and AF0/1EM=1 controls, the two CC:256 D5
  trial rows, the four retired-budget ZZ tiles, and the two at-budget ZZ
  controls) pass Tensile's own `NumElementsToValidate=128` reference
  validation on gfx90c — same pipeline Tensile uses for its own CI.
  The D5 trial row is decked and cited; the R8 1/2/4-assert rows are already
  the emission path; the decision between "SGEMM-style AF4/4 everywhere at
  CC:256/512" and "keep AF2/2" belongs to the owner's TTY perf run. GPU leg
  is legality only — no perf bars claimed anywhere; no adoption until TTY
  comparison lands.
- **LDS gate calibration vs Tensile's `Z: reg=4` — DECIDED 2026-11-14.**
  Owner call: `BYTES_PER_ELEMENT["Z"] = 16`, `LDS_BUDGET` kept at 16384. The
  six D2/D3 trial rows were retired; the ZZ deck keeps the at-budget ladder;
  `gfx90c_theoretical_limits.md` §6.1 records the outcome.
- **Class B end-to-end.** `README.md` §7 + `docs/operator_runbook.md` have the
  routing; the gfx902 starter pair (research output) is the missing piece;
  it depends on C4 above.
- **Refactor-1 slop (still open).**
  `oto/runners/reporting.py`: the registry-read failure silently returns
  "no arm data" (a real fault is indistinguishable from a dry run), and the
  report-generation failure prints a warning and returns `None` instead of
  failing loudly — both are review-grade swallowed exceptions, open since
  the Refactor-1 pass.
- **Dead mutators in `oto/tensile/synthesis/db_patterns.py`.** The four
  `_<fam>_mutation_pattern` methods (`_ss/_dd/_cc/_zz`) are dead base-deck
  leftovers, not called by `synthesize_mutants`; `_ss_mutation_pattern`
  reads the nonexistent `FORWARD_KNOB_DOMAINS["GSU"]` (latent KeyError).
  Decision owed: delete, or wire them with real GSU domains (the family
  split is already in `db.FAMILY_KNOB_DOMAINS`).
- **`self.scheduler` legacy alias.** `scheduler` holds a
  `CandidateGenerator` (`oto/runners/driver.py`); renaming to
  `self.generator` is mechanical but touches many call sites.
- **`idx_cell_key` never created by the schema.** `oto/ledger/registry_core.py`
  `_INDEX_DDL` has no `idx_cell_key`; only the live registry carries one.
  A fresh DB misses it; add the index explicitly.
- **C2.5–C2.9 (mechanical `DeviceProfile` threading, explicit parameters)
  deferred by design.** Mechanism is equivalent via `set_profile`/`bound_profile`;
  high churn across call sites. Revisit when a third device lands.

- **2 × `oto doctor` warnings** (advisory; user's earlier call stands —
  do not silence them):
  - venv-not-active — the interpreter doing the work is `/usr/bin/python3`;
    all checks here pass on the system interpreter, as designed.
  - `run_20261029_152402` (started, never finished, 0 measured cells) —
    abandoned 2026-10-29; registry is append-only so `oto check db` keeps
    reporting it; not modified.
- **yolo26 (new toolchain) — acceptance re-verified 2026-11-14** on the
  ROCm 7.x nightly + rocm-libraries Tensile (`best_effort_library_rocmlibs`,
  torch 2.12.0+rocm7.15): `frames=1 ... person 0.87`, CPU NMS, MIOpen GEMM
  solver. The old library (`best_effort_library`, ROCm 6.4.4 / Tensile 4.44)
  reproducibly wedges this nightly: `HW Exception by GPU node-1 ... GPU Hang`.
  New library is the working one; the old one is stale against nightly.
- **Any GPU leg other than yolo26 (and explicit CC-256 D5 legality probes)** —
  forbidden without the owner's explicit whitelist. Keep GPU use to yolo26 + the
  D5 probe only; never overload the GPU.

## Recently closed (pointers, not restated here)

- **C2.5–C2.9 — all consumer reads migrated** to `loader.current_profile()`
  (2026-11-14, commits `06c21fd`, `dffec27`, `bea5672`); the
  `oto.device.peaks` constant set is gone.
- **Verifier evergreen** — `--base REF` on all five checks; nothing pinned to
  `2824c2f` anymore; `archive/` entries from before the overhaul are
  superseded. Loads gate `int(None)` crash found (and fixed) upstream.
- **CLI UX rework** — `python3 -m oto` front-end, Phases 1–4.
- **yolo26 acceptance (C8)** — GPU acceptance satisfied against the
  best-effort rocm-libraries Tensile library.
- **Verifier manifest** — `oto/tools/verifiers/drift_manifest.json` lists
  attested divergences for the split-era base and for the current
  evergreen check; a machine-checked `test_verifier_manifest`-style proof is
  not needed today — the checks themselves exit 1 on any unattested drift.

## How to read this file

Every completion moves to `changelog.md` (the project evolution log); the
full historical version of this register lives in `archive/incomplete_work_2026-11-14.md`.
Nothing here is actioned without the owner's eyes on the controlling
architecture (owner: Netherquark).
