# Contributing to oto
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


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

## Commit discipline

- One concern per commit; imperative subject lines.
- Never weaken a test or a guard to make it pass. If a failure is real, fix
  the cause and state it in the message.
- The verifier is a correctness surface: changes to emitter behaviour need an
  attestation in `oto/tools/verifiers/drift_manifest.json` with the reason,
  never a silenced check.
- `docs/incomplete_work.md` tracks **open** items; finished work moves to
  `docs/changelog.md`.

## Docs-first (update docs in the same change)

| If you change | Update |
|---|---|
| `oto/**/*.py` | module docstring; `docs/cli.md` if flags/help change |
| `docs/*.md` | `docs/README.md` registry row + `oto agent index` |
| `tests/` | keep suite green |
| `AGENTS.md` / `docs/developer/invariants.md` | keep Tier-0 ≤ 60 lines |

Do not create new `.md` files without a registry row; edit the existing doc
for that surface.

## Where things live

Module map + ownership contract: `claude.md` and `oto/README.md`. Docs are
class-tagged (operations docs vs reference docs) — see `docs/README.md` for the
boundary and the owner docs registry.
