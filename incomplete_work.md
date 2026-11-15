# Incomplete Work register (open items only)
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


Completed work lives in `changelog.md` and the docs ecosystem; decisions live
in `docs/`. This file retains only items that are genuinely still open. Do
not re-raise closed items without new information.

## Blocked — owner-gated (documented; do not re-raise without new information)

- **gfx902 C4/C7.1 — blocked on the owner's API key + human gate.**
  agent-1/agent-2 research for the gfx902 starter cannot run;
  `profiles/gfx902.json` cannot be accepted by a human who must sign off a
  device that is not on this box. Class-B flow rehearsed on a synthetic stub
  (`tests/test_class_b_rehearsal.py`, 16 tests); CPU-side toolchain ready
  (`ISA_TRIPLES` carries gfx902; Tensile client builds). Unblocking needs
  only the key + the human gate. See `docs/starter_pair.md`.
- **CC:512/256 `AssertFree0/1ElementMultiple=4` A/B — TTY-gated.**
  GPU legality verified (all 11 probes pass Tensile's
  `NumElementsToValidate=128` reference on gfx90c); the two AF4/4 rows ship
  in `phases.yaml`. Paired-widen vs AF2/2 and the pure baseline will be
  measured when the overnight run resumes (`oto tune` on the owner's TTY).
  No performance claim exists anywhere until that measurement.
- **Acceptance reports / drift-manifest attestation.** Machine-local
  `acceptance_report.{json,html}` were overwritten in the v1-readiness
  audit; byte comparison confidence does not exist. The drift manifest
  stands at its last re-attestation (2026-11-15, 45th entry). Re-attestation
  is a deliberate on-machine act.
- **2 × `oto doctor` warnings (advisory; user's call stands — do not
  silence):** venv-not-active; abandoned run `run_20261029_152402`.

## Open items

- **C4 — gfx902 starter research** (agent-1 candidate census + agent-2
  per-class research report). Blocked on the owner's API key.
- **C7.1 — gfx902 starter profile** (`profiles/gfx902.json`). Blocked on C4
  and the human verification gate.
- **gfx902 TTY work** — `oto tune` / `oto report` / `oto check
  library-parity` / `oto library best-effort` on the target silicon.
- **Tensile client on a fresh machine** — compiled artifact, not committed;
  re-run `scripts/build_tensile_client.sh`.
- **CC:256 Option B (SGEMM-style adoption)** — not implemented; decision
  belongs to the user.
- **LDS boundary probes** — 4 above-budget ZZ tiles + 2 at-budget controls
  through direct Tensile, pending the client binary.
- **Any GPU leg other than yolo26 and the D5 CC-256 legality probes** —
  forbidden without the owner's explicit whitelist.

## How to read this file

Every completion moves to `changelog.md` (the project evolution log); the
full historical register survives in git history. Nothing here is actioned
without the owner's eyes on the controlling architecture (owner: Netherquark).