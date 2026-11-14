# Incomplete Work register (consolidated 2026-11-14)

The 1,007-line archived register was consolidated and deleted; its
contents were folded into the docs ecosystem the same day (GPU/LDS
validation doc `docs/gfx90c_theoretical_limits.md` §6.1, floor triage in
`docs/results.md` §8–§9, GSU/domain notes in `docs/gfx90c_tuning_guide.md`, the
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
- **CC:256/512 `AssertFree0/1ElementMultiple=4` — ADOPTED 2026-11-14 (owner
  decision, Option B: the vendor's SGEMM recipe).** GPU legality was verified
  first (all 11 probes pass Tensile's `NumElementsToValidate=128` reference on
  gfx90c). The two AF4/4 rows (`_af4em4`, CC:256/CC:512 `mt64x64x8/tt4x4/VW2/AF0/1EM=4`)
  now ship in `phases.yaml` as first-class CC rows (`oto check candidates`:
  280 checked, 0 illegal); the D5 pilot row graduated; `DECISION_TRIAL_TILES`
  keeps only D1. What remains open: TTY A/B against the AF2/2 paired-widen and
  the AF1 baseline rows — adoption makes AF4/4 the reference deck, but no
  perf bars are claimed anywhere; the winner is measured in the overnight run,
  not asserted here.
- **LDS gate calibration vs Tensile's `Z: reg=4` — DECIDED 2026-11-14.**
  Owner call: `BYTES_PER_ELEMENT["Z"] = 16`, `LDS_BUDGET` kept at 16384. The
  six D2/D3 trial rows were retired; the ZZ deck keeps the at-budget ladder;
  `docs/gfx90c_theoretical_limits.md` §6.1 records the outcome.
- **Class B end-to-end.** `README.md` §7 + `docs/operator_runbook.md` have the
  routing; the gfx902 starter pair (research output) is the missing piece;
  it depends on C4 above.
- **Refactor-1 slop (still open).**
  `oto/runners/acceptance_reporting.py`: the registry-read failure silently returns
  "no arm data" (a real fault is indistinguishable from a dry run), and the
  report-generation failure prints a warning and returns `None` instead of
  failing loudly — both are review-grade swallowed exceptions, open since
  the Refactor-1 pass.
- **Dead mutators in `oto/tensile/synthesis/donor_patterns.py`.** The four
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
- **Owner decision — 9.9 GB nightly tarball deletion** (the extracted SDK is in use under `dist-7.15.0a20260728/`); blocked on the owner's word.
- **HIP_PATH canonical choice** — the ROCm nightly venv vs the extracted `dist-7.15.0a20260728/` SDK; no code blocker, owner confirms.
- **gfx90c tuning guide → caveman-full rewrite** — the guide is professional prose today; the owner wants caveman-full for it.
- **AGENTIC agentic-consult implementation** — the agentic `docs/potential_configs.md` synthesis design was never implemented; the scratch design doc was removed 2026-11-14; implement only if the owner wants it (re-derivable from `docs/operator_runbook.md` + `docs/operator_campaign.md`).

- **Any GPU leg other than yolo26 (and explicit CC-256 D5 legality probes)** —
  forbidden without the owner's explicit whitelist. Keep GPU use to yolo26 + the
  D5 probe only; never overload the GPU.

## Recently closed (pointers, not restated here)

- **C2.5–C2.9 — all consumer reads migrated** to `loader.current_profile()`
  (2026-11-14, commits `06c21fd`, `dffec27`, `bea5672`); the
  `oto.device.peaks` constant set is gone. The explicit-parameter threading the
  2026-11-14 round deferred was completed the same day: every profile-consuming
  function in the package now takes `profile=None` resolved through the
  `oto.device.loader.resolve_profile` choke point, internal call sites thread
  the caller's profile explicitly (qualified resolution + AST-verified, never
  bare-name matching), and the import-time frozen captures are gone (all lazy
  derivation). Verified by the second-profile tests, the new
  `test_explicit_profile_threading.py` (end-to-end through `validate_config`),
  and the verifier, whose ast-equivalence check now recognises the Refactor 2
  signature shape evergreen. Commits `e5ebdc4` (choke point + gates),
  `ae99b75` (sweep), `a7500ea` (verifier), `0807157` (threading test).
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
