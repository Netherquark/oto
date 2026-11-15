# Incomplete Work register (open items only)
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


Completed work lives in `docs/changelog.md` and the docs ecosystem; decisions live
in `docs/`. This file retains only items that are genuinely still open. Do
not re-raise closed items without new information.

## Blocked — owner-gated (documented; do not re-raise without new information)

- **gfx902 C4/C7.1 — blocked on the owner's API key + human gate.**
  agent-1/agent-2 research for the gfx902 starter cannot run;
  `profiles/gfx902.json` cannot be accepted by a human who must sign off a
  device that is not on this box. Class-B flow rehearsed on a synthetic stub
  (`tests/test_class_b_rehearsal.py`, 16 tests); CPU-side toolchain ready
  (`ISA_TRIPLES` carries gfx902; Tensile builds and assembles gfx902).
  Unblocking needs only the key + the human gate. See `docs/operator/starter_pair.md`.
- **CC:512/256 AF0/1ElementMultiple=4 A/B — perf measurement TTY-gated.**
  Legality on silicon is closed: all six CC candidate rows built and ran on
  gfx90c with Tensile's `NumElementsToValidate=128` validation PASS (2026-11-15,
  run_20261115_175934; matrices ≤ 512³). This clears the *correctness* gate, not
  the tuning decision. The paired-widen vs AF4/4 *perf* A/B (clock-controlled,
  median-of-seeds, floor-referenced) will be measured when the overnight run
  resumes (`oto tune` on the owner's TTY). No performance claim exists anywhere
  until that measurement; the raw medians from the 2026-11-15 single pass
  (clocks uncontrolled) are not a tuning verdict.
- **Acceptance reports / drift-manifest attestation.** Machine-local
  `acceptance_report.{json,html}` were overwritten in the v1-readiness audit;
  byte comparison confidence does not exist. The drift manifest stands at its
  last re-attestation (2026-11-15). Re-attestation is a deliberate on-machine act.
- **`oto doctor` advisory warnings (advisory; user's call stands — do not
  silence):** venv-not-active (the interpreter is a bare `python3`, not the
  nightly venv — harmless for oto core, masks missing rocm/torch packages for
  PYTorch paths); and an abandoned run `run_20261029_152402` recorded in
  `runs` (status not completed/interrupted). The Oct-29 abandoned-run warning
  no longer surfaces because a completed run (`run_20261115_175934`) is now the
  newest, but the stale row remains in the append-only ledger and is kept as
  history, not deleted.

## Open items

- **C4 — gfx902 starter research** (agent-1 candidate census + agent-2
  per-class research report). Blocked on the owner's API key.
- **C7.1 — gfx902 starter profile** (`profiles/gfx902.json`). Blocked on C4
  and the human verification gate.
- **gfx902 TTY work** — `oto tune` / `oto report` / `oto check
  library-parity` / `oto library best-effort` on the target silicon.
- **Tensile client on a fresh machine** — compiled artifact, not committed;
  re-run `scripts/build_tensile_client.sh`.
- **Nightly `dist-7.15.0a20260728/` tarball extract (8.2 GB)** — installed but
  unused by the current `.env` (which points at the 1.4 GB python-sdk
  `_rocm_sdk_core`). Deletion is the owner's call; the tarball itself is
  already gone.
- **Any GPU leg other than the 2026-11-15 CC legality probes** — forbidden
  without the owner's explicit whitelist.

## How to read this file

Every completion moves to `docs/changelog.md` (the project evolution log); the
full historical register survives in git history. Nothing here is actioned
without the owner's eyes on the controlling architecture (owner: Netherquark).
