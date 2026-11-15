# Incomplete Work register (consolidated 2026-11-14)

The 1,007-line archived register was consolidated and deleted; its
contents were folded into the docs ecosystem the same day (GPU/LDS
validation doc `docs/gfx90c_theoretical_limits.md` §6.1, floor triage in
`docs/gfx90c_results.md` §8–§9, GSU/domain notes in `docs/gfx90c_tuning_guide.md`, the
verifier-bringup history in `changelog.md`). The git object holds the
pre-fold snapshot; recovered in any case. Only the *open* items are kept
live here; completed work lives in `changelog.md`, decisions in `docs/`.

## Blocked — owner-gated (documented; do not re-raise without new information)

- **gfx902 C4/C7.1 — blocked on the owner's API key.** agent-1/agent-2 research
  for the gfx902 starter cannot run; `profiles/gfx902.json` cannot be accepted by
  a human who must sign off a device that is not on this box. The class-B flow is
  fully rehearsed on a synthetic stub (`tests/test_class_b_rehearsal.py`,
  16 tests), the CPU-side toolchain is ready (`ISA_TRIPLES` carries gfx902,
  `ISA_TRIPLES["gfx902"] == (9, 0, 0x02)`; the Tensile client builds and is OK),
  so unblocking needs only the key + the human gate. Detail below: "C4" and "C7.1"
  entries under Open items.
- **Tensile client — BUILT and verified 2026-11-15.** `oto doctor` now reports
  `21 ok / 0 failures` for the client row (`build/client/tensile-client` exists and
  runs `--version`; GPU untouched). Built with `scripts/build_tensile_client.sh`
  against the full extracted TheRock 7.15.0a20260728 SDK (the venv's `include/hip`
  shadows nightly headers; the full dist is the only complete prefix on this box).
  `tests/test_build_tensile_client.py` locks the failure paths.
- **CC:512/256 `AssertFree0/1ElementMultiple=4` (AF4/4) vs AF2/2 paired-widen — measured nowhere, valid nowhere, claimed nowhere.**
  The A/B is TTY-gated and unscheduled; it happens only when the overnight run resumes
  (`oto tune` on the owner's TTY). Until then no performance claim exists anywhere —
  not in docs, not in the deck, not in reports. Detail below: the CC entry under Open items.
- **Acceptance reports / drift-manifest attestation.** The machine-local
  `acceptance_report.{json,html}` were overwritten in the v1-readiness audit;
  byte comparison confidence does not exist (entry under Open items). The
  `oto/tools/verifiers/drift_manifest.json` attestation stands at its last
  re-attestation (2026-11-15, 45th entry); it is not invalidated by docs work,
  but it has not been re-attested since either — re-attestation is a deliberate
  on-machine act, not an assumption to make here.

## Open items
- **gfx902 Tensile port step — the blocker that remains before any gfx902 phase can build (owner-gated by design).**
  CPU-only proof on this box (`oto check tensile-build --arch gfx902`) fails at Tensile, not at oto:
  `KeyError: globalParameters["AsmCaps"][(9, 0, 2)]` at `SolutionStructs.py:3023
  supportsPreloadKernelArguments`. The pinned rocm-libraries checkout contains **zero** occurrences
  of gfx902/(9,0,2) — upstream ships no gfx902 support (expected: an unsupported arch).
  Verified independently, CPU-only: the nightly clang assembles gfx902 v_fma_f64 (ISA is real),
  and refuses gfx902 MFMA with `instruction not supported on this GPU (gfx902)`.
  The port therefore needs the same 3-entry patch the gfx90c port landed on 2026-09-19:

  1. `Tensile/Common.py` — `SupportedISA` gains `(9, 0, 2)`;
  2. `Tensile/Common.py` — `architectureMap["gfx902"] = "vega10"` (the sibling arch schedule);
  3. `Tensile/AsmCaps.py` — a `(9, 0, 2)` capabilities entry (as with gfx90c: written against the
     real LLVM encoding; the caps derive per-instruction from the assembler at runtime — the
     entry is the bookkeeping the port needs, not a hand-guessed table).

  This is owner work, by the same rule that kept the gfx90c patch owner-landed. The answer to
  "what is left before the API key" is: this patch (or the owner's instruction to prepare it),
  then profiles/gfx902.json (human-verified), then the key. Nothing else.


- **C4 — gfx902 starter research** (agent-1 candidate census + agent-2
  per-class research report). Blocked on the owner's API key.
  (`docs/gfx902_starter.md` has the public identity + open questions; the
  research prompt only runs once the key exists.)
- **C7.1 — gfx902 starter profile** (`profiles/gfx902.json`). Blocked on C4:
  a human must review the numbers and accept the profile; testing it blind
  would pretend gfx902 hardware exists, which it does not here. The gate
  tests already exercise a `dataclasses.replace`-derived synthetic device.
  **gfx902 readiness (mechanical) closed 2026-11-15** by the CI-removal arc:
  class-B end-to-end commands walked in an isolated stub (`tests/test_class_b_rehearsal.py`, 16 tests), agent prompts now carry ISA-level directed questions with ISA-manual citations, tuning-context template is a scaffold with profile-derived fill, the ISA-gating proof refuses unknown arches with an actionable message (`oto/checks/tensile_build_probe.py:_pin_isa`), and the first-light checklist is at `docs/starter_pair.md §0 (bring-up order)`. The tarball has been deleted (1.6 GB).
- **CC:256/512 `AssertFree0/1ElementMultiple=4` — CLOSED as a decision (owner's word, 2026-11-15).** GPU legality was verified: all 11 probes pass Tensile's `NumElementsToValidate=128` reference on gfx90c. The two AF4/4 rows ship in `phases.yaml` as first-class CC rows. TTY A/B (AF4/4 vs AF2/2 paired-widen and the pure baseline) will be measured when the overnight run resumes — no perf claim appears anywhere, and none is expected to appear until that
  measurement exists. (The question asked on 2026-11-14 is
  formally closed: the experiment is planned, not undone.)
- **Class B end-to-end.** `README.md` §7 + `docs/operator_runbook.md` have the
  routing; everything that can run without the key has been verified
  (`tests/test_class_b_rehearsal.py`: agent generate/consult/index/candidate/stats/verify-all/run-snapshot-diff/check-candidates/doctor/library-best-effort/preflight/report all pass on a synthetic stub). What remains is the API-key-backed research phase and the human gate — both ownered.
- **F-REPORT-4 — like-for-like degenerate paths are not marked in the JSON.** The report falls back to per-run analytics without a like-for-like filter when `_native_analytics_all_runs` is empty, and nothing flags the report provenance. Minor, single-site change to the payload (would add a `protocol_fallback` or similar marker to `<codename>_results/acceptance_report.json`). Deferred for owner review — a new payload field needs the downstream consumers to cope first.
- **Refactor-1 slop (closed 2026-11-15).** Both swallowed exceptions are fixed:
  registry-read failures propagate, and report-generation failures raise loudly.
  The four dead `_<fam>_mutation_pattern` methods are deleted (never called by
  `synthesize_mutants`); `self.scheduler` is now `self.generator` everywhere;
  `idx_cell_key` is created by the schema (`_EXPRESSION_INDEX_DDL`). See the
  changelog 45th entry — no further owner decision needed.
- **Toolchain honesty (closed 2026-11-15, see 45th changelog entry).**
  `OTO_TENSILE_CLIENT` pointing at a missing path is a hard error; `oto doctor`
  reports the Tensile client row — it now reads OK (client built 2026-11-15 with
  `scripts/build_tensile_client.sh`; see the Blocked section above). GPU legs
  other than yolo26 remain whitelist-gated.

- **2 × `oto doctor` warnings** (advisory; user's earlier call stands —
  do not silence them):
  - venv-not-active — the interpreter doing the work is `/usr/bin/python3`;
    all checks here pass on the system interpreter, as designed.
  - `run_20261029_152402` (started, never finished, 0 measured cells) —
    abandoned 2026-10-29; registry is append-only so `oto check db` keeps
    reporting it; not modified.
- **Agent external review — overwritten audit reports (CLOSED 2026-11-15).**
  Four `acceptance_report.{json,html}` artifacts (under `gfx90c_results/` and
  `gfx90c_runs/run_20261009_205427/`) were overwritten by an accidental
  regeneration with today's timestamps rather than a byte-identical restore.
  Contents are consistent with the ledger (20 WIN / 18 TIE / 0 LOSS, 7 ORANGE;
  run `run_20261009_205427`); the original bytes are unrecoverable.
  Treat the current files as the canonical artifact going forward; do not
  re-compare against the pre-overwrite numbers. Owner is aware — closed on
  owner's word.
- **`oto doctor` FAIL (`Tensile client`) — RESOLVED 2026-11-15.** The benchmark
  client is built and is at
  `<TENSILE_ROOT>/build/client/tensile-client`; `oto doctor` reports it OK
  (21 ok, 0 FAIL). Build: `scripts/build_tensile_client.sh
  --rocm-prefix <full-SDK-prefix> --tensile-root <TENSILE_ROOT>`
  (contract: `docs/toolchain_client.md`). The client is a compiled artifact and
  is not committed; a fresh machine re-runs the same script.
- **CI removal (CLOSED 2026-11-15, owner's word).** There is no CI in this repo.
  The pre-commit gate is the deterministic on-machine suite
  (`python3 -m pytest -q`) with `OTO_GUARD_FILES=1` for the changed-files fast
  path; every guard now falls back to the full scan on a clean tree (the fast
  path was previously vacuously green on an empty diff). Owner confirmed they
  asked for no CI.
- **yolo26 (new toolchain) — acceptance re-verified 2026-11-14** on the
  ROCm 7.x nightly + rocm-libraries Tensile (`best_effort_library_rocmlibs`,
  torch 2.12.0+rocm7.15): `frames=1 ... person 0.87`, CPU NMS, MIOpen GEMM
  solver. The old library (`best_effort_library`, ROCm 6.4.4 / Tensile 4.44)
  reproducibly wedges this nightly: `HW Exception by GPU node-1 ... GPU Hang`.
  New library is the working one; the old one is stale against nightly.
- **Unrecoverable report artifacts (from the v1-readiness audit).** The audit
  overwrote `gfx90c_results/acceptance_report.{json,html}` and
  `gfx90c_runs/run_20261009_205427/acceptance_report.{json,html}` while running a
  "read-only" check whose live-registry path rewrites the live A/B report. No
  byte-identical restore exists (the audit's regeneration reproduces the same
  envelope — 20 WIN / 18 TIE / 0 LOSS, 7 ORANGE, 38 cells — but with new
  timestamps). These files are machine-local (gitignored); no functional impact;
  flagged here so no one later claims byte-comparison confidence they do not have.
- **9.9 GB nightly tarball — DELETED 2026-11-15 (owner's word).**
  `therock-dist-linux-gfx90c-7.15.0a20260728.tar.gz` (1.6 GB) deleted; the extracted dist at
  `/home/netherquark/rocm-nightly-venv/dist-7.15.0a20260728/` is retained and remains functional
  (amdclang 23.0.0git, TheRock 7.15.0a20260728, gfx90c listed in dist_info amdgpu targets).
- **HIP_PATH canonical choice — DECIDED 2026-11-15 (owner's word).**
  Keep using the rocm-nightly venv (`/home/netherquark/rocm-nightly-venv/lib/python3.14/site-packages/_rocm_sdk_core`).
  Every proven fact in this repo (yolo26 acceptance 2026-11-14, CC probe on 128-element workloads,
  the Tensile build) was measured against that venv. The extracted dist is redundant once the
  venv works; only point HIP_PATH at the dist if you specifically need a second version-locked
  ROCm independent from torch's venv. No code/doc change needed in the repo.

- **Any GPU leg other than yolo26 (and explicit CC-256 D5 legality probes)** —
  forbidden without the owner's explicit whitelist. Keep GPU use to yolo26 + the
  D5 probe only; never overload the GPU.

## Recently closed (pointers, not restated here)

- **AGENTIC consult implemented** — `oto agent consult [starter] [--with-docs]`
  (`8b73424`); CPU-only census consult emits `<codename>_potential_configs.md`;
  `docs/potential_configs.md` itself is hand-maintained (the device-independent
  methodology; the gfx90c record lives in `docs/gfx90c_tuning_guide.md` §13) —
  it is never auto-generated.
  All one-shot plans in git history now audited; changelog 43rd entry.
- **LDS gate calibration vs Tensile's `Z: reg=4` — DECIDED 2026-11-14.**
  Owner call: `BYTES_PER_ELEMENT["Z"] = 16`, `LDS_BUDGET` kept at 16384. The
  six D2/D3 trial rows were retired; the ZZ deck keeps the at-budget ladder;
  `docs/gfx90c_theoretical_limits.md` §6.1 records the outcome.
- **gfx90c tuning guide → caveman-full rewrite — DONE 2026-11-14.**
  `docs/gfx90c_tuning_guide.md` rewritten in strict caveman-full style; all
  technical content intact; ~28% smaller.

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
full historical version (`docs/work_archive_2026-11-14.md`, the 1,007-line register) was folded into the ecosystem and deleted in `d8068f9`; it survives in git history via `git show d8068f9^:docs/work_archive_2026-11-14.md`.
Nothing here is actioned without the owner's eyes on the controlling
architecture (owner: Netherquark).
