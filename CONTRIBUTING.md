# Contributing to oto

Thanks for helping. This document is the practical path from a fresh clone to a
review-ready change.

## Setup

```bash
git clone <repo> && cd oto
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt   # pinned known-good set + pytest + ruff
python3 -m pytest -q                  # CPU-only; the GPU legs are whitelisted
```

Requirements are pinned for reproducibility (`requirements.txt` = runtime,
`requirements-dev.txt` = suite + lint). Bump pins only deliberately, as their
own commit.

## Before you push

- `ruff check oto tests` is clean under `ruff.toml` (line-length and docstring
  rules deliberately not gated).
- `python3 -m pytest -q` is green **and you have read the exit code** — never
  hand-wave "it passed".
- `python3 -m oto verify all --base-ref 2824c2f` passes (split-era
  comparison; the default base is `HEAD~1`, the evergreen per-commit check).
- If you touched the CLI help, run `python3 -m oto help --write docs/cli.md` —
  `docs/cli.md` is pinned byte-identically to the parser output and the test
  suite enforces it.

## GPU policy (hard rule)

No GPU legs outside the owner's explicit whitelist (`claude.md`), and no GPU
perf claims without a TTY session on the target box. CPU-only proofs are
expected and preferred wherever they exist (`oto check candidates`,
`oto verify all`, the legality probes). Never overload the GPU.

## Commit discipline

- One concern per commit; imperative subject lines.
- Never weaken a test or a guard to make it pass. If a failure is real, fix
  the cause and state it in the message.
- The verifier is a correctness surface: changes to emitter behaviour need an
  attestation in `oto/tools/verifiers/drift_manifest.json` with the reason,
  never a silenced check.
- `incomplete_work.md` tracks **open** items; finished work moves to
  `changelog.md`.

## Where things live

Module map + ownership contract: `claude.md` and `oto/README.md`. Docs are
class-tagged (operations docs vs reference docs) — see `docs/README.md` for the
boundary and the owner docs registry.
