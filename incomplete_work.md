# Incomplete Work register (consolidated 2026-11-14)

The 1,007-line register was archived at
`docs/work_archive_2026-11-14.md` — git has it, so no record was lost;
only the *open* items are kept live here. Completed work lives in
`changelog.md`; decision history lives in `docs/` and in the
relevant ecosystem doc.

## Open items

- **C4 — gfx902 starter research** (agent-1 candidate census + agent-2
  per-class research report). Blocked on the owner's API key.
  (`docs/gfx902_starter.md` has the public identity + open questions; the
  research prompt only runs once the key exists.)
- **C7.1 — gfx902 starter profile** (`profiles/gfx902.json`). Blocked on C4:
  a human must review the numbers and accept the profile; testing it blind
  would pretend gfx902 hardware exists, which it does not here. The gate
  tests already exercise a `dataclasses.replace`-derived synthetic device.
- **CC:256 `AssertFree0/1ElementMultiple=4` — the empirical half is
  unverified.** CPU-side gate (candidates.py / deck_review) landed and is
  proven against every shape; the correctness comparison against a reference
  CGEMM kernel on real silicon needs the owner's TTY (Phase 5).
- **LDS gate calibration vs Tensile's `Z: reg=4`.** `oto/tensile/gates/vgpr_model.py`
  `BYTES_PER_ELEMENT["Z"] = 8`; Tensile's `numBytes() = 4 * 4 = 16` and
  `FAMILY_BYTES_PER_ELEMENT["ZZ"] = 16` already. *Owner decision required*
  before changing either: the gate policy is calibrated, and the file used by
  the occupancy gate (`LDS_BUDGET`) and the byte table must move together.
  Estimated ~1 h on a quiet machine with a CPU-only build proof to measure
  the false-rejection rate. Do not touch either constant until decided.
- **Class B end-to-end.** `README.md` §7 + `docs/operator_runbook.md` have the
  routing; the gfx902 starter pair (research output) is the missing piece;
  it depends on C4 above.
- **2 × `oto doctor` warnings** (advisory; user's earlier call stands —
  do not silence them):
  - venv-not-active — the interpreter doing the work is `/usr/bin/python3`;
    all checks here pass on the system interpreter, as designed.
  - `run_20261029_152402` (started, never finished, 0 measured cells) —
    abandoned 2026-10-29; registry is append-only so `oto check db` keeps
    reporting it; not modified.
- **Any GPU leg other than yolo26** — forbidden without the owner's explicit
  whitelist. Keep CPU-only.

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
