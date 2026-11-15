# Developer agent ecosystem plan (read-only)
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


**Status: plan only.** Based on agentic-doc best practices (progressive
disclosure, single source of truth, ownership headers, freshness checks,
docs-first). Proposes how to reshape the developer (Class A) ecosystem.

## 1. Problems today
- `claude.md` is ~572 lines: acts as both entry point and reference manual.
  Agents lose the middle; compliance drops beyond ~150–200 instructions.
- Developer docs are inconsistent in depth/size; no ownership/freshness headers.
- No explicit "if you change X, update Y" mapping; agents create orphan files.
- `docs/README.md` registry is the only index; no lightweight AGENTS.md-style
  pointer at repo root for agents that read root first.

## 2. Target shape (progressive disclosure)

### Tier 0 — root entry (≤ 60 lines): `AGENTS.md` (new) + `claude.md` (slimmed)
- Identity, hard constraints ("never"/"must"), build/test/lint commands,
  documentation index with paths + one-line descriptions, commit conventions.
- No product requirements, no architecture details, no feature designs.

### Tier 1 — on-demand reference: `docs/*.md`
- Each doc owns one topic; single source of truth.
- Header block: `owner`, `last-reviewed`, `review-interval`.
- Rule stated first, then rationale; examples + counter-examples where ambiguous.

### Tier 2 — archive: `docs/archive/` or `archive/`
- Superseded docs marked `status: archived`; never executed as current truth.

## 3. Specific changes
1. Split `claude.md`: move §2.0 invariants (keep ~60 lines) into `AGENTS.md`;
   move the rest into `docs/invariants.md` (new) or existing `implementation_plan.md`.
2. Add `AGENTS.md` at repo root with the documentation map table
   (code glob → doc file) and "do not create new doc files" rule.
3. Add ownership headers to every `docs/*.md` (start with dev-class docs).
4. Add `check-doc-freshness` style guard: warn when `last-reviewed` exceeds
   `review-interval` (lightweight, runs in pre-commit / CI-less suite).
5. Enforce docs-first in `CONTRIBUTING.md`: mapping table + "update docs in
   same change".
6. Co-locate module docs only where non-obvious invariants exist (per
   docs-first workflow); do not create by default.
7. Mark archived/superseded docs (`archive/`, old context files) as
   `status: archived`.

## 4. Verification
- `claude.md` / `AGENTS.md` ≤ 60 lines (guard test).
- All dev-class docs carry owner + last-reviewed headers (guard test).
- `docs/README.md` registry stays the single index; `AGENTS.md` only points to it.
- No new orphan `.md` files without registry entry.

## 5. Out of scope
- Rewriting docstring content (separate pass).
- Renaming files (mass rename; needs tests).