# CLI UX rework plan — oneshot evergreen (2026-11-13)

Status: **IMPLEMENTED (Phases 1-4).** All 25 questions answered and resolved. Full suite green 2026-11-13 (1044 passed / 8 skipped / 242 subtests).
Phases 1-4 landed as commits 362744b..423ecbe. Remaining: stdout/stderr contract
(narration already redirected to stderr for mutating commands) and deeper
docs rewrite (command references updated, full Class B rewrite pending).

Motivation: the current CLI is "impossible to make sense of" — 11 root shims
plus `-m` module invocations, ~50 flat flags on one mega-parser, stale/broken
examples, no `oto` noun-verb vocabulary, output mixing stdout/stderr, errors
that aren't remediation. This plan reworks the surface to a single `oto`
front with verb-first subcommands, following POSIX Issue 8, the GNU coding
standards, 12-factor CLI conventions and clig.dev (Command Line Interface
Guidelines).

**Oneshot evergreen**: no legacy shims, no backwards-compat aliases, no pipx
installable package, no Windows support. Each commit is a discrete step even
if not a fully functional chunk — git is the backup. Docs ecosystem updated
with new nomenclature in the same pass.

## 1. What exists today (evidence)

**Three inconsistent invocation mechanisms, none of which are "the CLI":**
- 11 root shims that only `sys.path.insert` and call `oto.tools.*:main`
  (`all_runs.py`, `check_db.py`, ...).
- Package modules meant to be run as scripts — `python3 -m oto.metrics.render_status --help`
  **crashes today** (`No module named 'oto'`) — and `README.md:365` plus that
  module's own `--help` example reference `python3 run_status.py`, which
  **does not exist**.
- Module `-m` invocations (`python3 -m oto.metrics.render_status`), which is what actually works.

**One mega-parser**: `port_tensile.py` holds ~50 flat flags in a single
namespace — no subcommands, no grouping in `--help`, mutually-exclusive flags
unmarked, cross-flag semantics by convention (`--report` and `--best-library`
take optional values, so composition with other flags is ambiguous). `--stage`
is a hidden routing table; `--auto` is a second universe of interactive
questions where Q1 (rerun_illegal) has no flag equivalent but Q2/Q3 do
(`--release-under-specified` / `--release-unreproducible`), and the meaning of
q1–q3 must be learned from `--yes`'s docstring.

**Naming is internal jargon, not user tasks**: `port_tensile`? `all_runs`?
`check_retirement`? Five `check_*` scripts with different nouns, `chart.py`,
`verify_all` (refactor verifiers) vs `verify_run` (corpus snapshots) — a
whole verifier vocabulary with no shared frame. Nothing answers "how do I see
current status?" without reading `docs/README.md`.

**Output discipline drifts**: `--json` exists piecemeal (`all_runs --json`,
`render_status --json`) but not on the driver; logs and reports interleave on
stdout; no `NO_COLOR`/`--no-color`; pace/ETA mixed with real output;
`--live` repaint machinery defaults on.

**No feedback channel to humans**: no `oto doctor`-style command for the
venv / TENSILE_ROOT / compiler-mismatch failure we hit when moving to the
nightly; errors are raw argparse rejections or tracebacks; no next-step
hints; no `--version`.

## 2. Design principles (clig.dev / POSIX / GNU / 12-factor CLI)

Human-first, predictable, discoverable, conversational:

- **Verb-first, noun-scoped subcommands**, max two levels (`git`,
  `docker container create`, clig "Subcommands"). One canonical flag per
  concept; full-length flags mandatory; shorts reserved for the common ones.
- **Stdout = data, stderr = narration/diagnostics**; machine mode via
  `--json`; `--quiet` / `--verbose` on every command. (clig "The Basics", "Output")
- **Help leads with examples**; bare invocation prints a concise (`jq`-style)
  orientation; `-h` shows full reference. (clig "Help")
- **Errors become documentation**: known failure modes rewrite as remediation;
  unknowns get the traceback saved under `<base>/logs/` + a report URL.
  (clig "Errors")
- **Prompt only on a TTY**; every question skippable by flag or `--no-input`;
  CI gets `--yes` / `OTO_YES`. (clig "Interactivity")
- **Idempotent, dry-runnable, scriptable**: `--dry-run` everywhere state
  changes; exit codes 0/1/2. (clig, GNU standards)
- **Progress when work is slow; suggest the next command on success.**
  (clig "Robustness")
- **No backwards compat**: old flag names are not aliased; old shims are
  deleted, not deprecated. The migration is a clean break.

## 3. Proposed command surface

One `oto` dispatcher (repo-root `oto` script + `oto/__main__.py`; no pipx
installable package, no packaging theater). Verb-first with four noun groups.
Old root shims are deleted, not deprecated.

| New command | Replaces | Notes |
|---|---|---|
| `oto` (bare) | — | 10-line orientation + `oto status` summary + top tasks |
| `oto tune [--budget N] [--mutations M] [--resume] [--include-illegal] [--include-underspecified] [--include-unreproducible] [--yes\|--no-input]` | `port_tensile.py [--auto]` | the convergence loop; all three floor questions get flags |
| `oto bench [--limit N] [--ref-shapes 256,512] [--resume] [--refresh] \| --native` | `--gfx900-reference` / `--native` | reference floor vs native tuning split explicit |
| `oto bench --targets … [--family SS] [--pattern …] [--shape …] [--dry-run]` | flat-flag selectors | one scope grammar, same in every command |
| `oto status [--watch SEC] [--thermals] [--json] [--plan KEY=VAL…]` | `python3 -m oto.metrics.render_status` | the ETA/panel lives here; bare = today's behaviour |
| `oto report [--run ID] [--json]` | `--report` | acceptance report regen |
| `oto library best-effort [--dest PATH] [--protocol-basis family\|any\|single\|partial]` | `--best-library` | CPU-only carve |
| `oto library verify` / `oto library build-proof` | `check_library_parity.py`, `check_tensile_build.py` | parity + build-proof assertion |
| `oto check candidates` | `check_candidates.py` | deck linter |
| `oto check retirement` | `check_retirement.py` | retirement assertion |
| `oto check db` | `check_db.py` | registry integrity |
| `oto doctor` | nothing | diagnostics: TENSILE_ROOT resolves? TheRock toolchain real? GPU present? `.env` honoured? Prints per-line pass/fail with remediation — the "why doesn't it work on my box" command |
| `oto verify all` / `oto verify run {snapshot,diff,telemetry,cheapest}` | `verify_all.py`, `verify_run.py` | keep semantics exactly |
| `oto consolidate` | `consolidate.py` | deck consolidation |
| `oto stats` | `all_runs.py` | cross-run view; `--json` native |
| `oto chart` | `chart.py` | figures |
| `oto docs generate [STARTER]` | `--generate-device-docs` | agent-1/agent-2 doc generation |
| `oto version` / `oto help [topic]` | — | `oto help <topic>` pages via `less -FIRX` on a TTY |

No backwards compat: old flag names are not aliased; old shims are deleted.
Shorter flag names on the new surface: `--include-illegal`, `--include-underspecified`,
`--include-unreproducible` (no aliasing of the older `--release-*` spellings).

## 4. Global conventions (enforced in `oto/cli/` scaffold, not per-command)

- **Flags**: default-on `--live` stays but is TTY-guarded; every command has
  `-h/--help`, `--json`, `-q/--quiet`, `-v/--verbose` (stderr escalation),
  `--no-input`, `--no-color` (+ `NO_COLOR`, inert when not a TTY). New shorts
  reserved: `-q -v -h -n -y`. Canonical spellings: `--base` (no `--base-dir`
  alias — one spelling).
- **Output**: data→stdout, narration/logs/ETA/errors→stderr; `--json` emits
  one JSON doc on stdout and **silences** narration; `--plain` reserved for
  future tabular greppability. Interactivity never on non-TTY; progress bars
  only on TTY; spinners → plain lines under pipes.
- **Exit**: `0` ok, `1` failure, `2` usage error (argparse native, POSIX);
  machine modes add one envelope `{"ok": false, "error": {code, hint}}`.
  GPU-loss abort stays visible (today's behaviour, kept).
- **Help**: three tiers — bare command = 8–10 line orientation ("You want to
  … → `oto …`"); `-h` = grouped sections with most-used flags first (clig) and
  **EXAMPLES before FLAGS**; `oto help <subcommand>` = the same text paged on
  a TTY. Every help includes one runnable `--dry-run` example first.
- **Errors**: a `oto/errors.py` rewrite table for the top failure modes
  (registry missing → "run `oto check db`"; TENSILE_ROOT unset → "set it in
  env or .env — see `oto doctor`"; GPU absent → the gfx note; interrupted
  run → "oto status" hint). Unknown → traceback→`logs/oto-<ts>.log` + "file
  this with the URL at the end of the log".
- **State changes disclosed**: commands that write the registry/deck announce
  what they changed and echo the next command (e.g. `oto check db` after a fix).
- **Idempotence**: `oto tune --dry-run --resume` is a pure listing; all read
  commands reconcile against the same loaders used today.

## 5. Implementation phases (each independently committable, preflight green per commit)

**Phase 0** (this document) — nothing lands.

**Phase 1 — scaffold + entry repair**
- New `oto/__main__.py`, repo-root `oto` script (`exec python3 -m oto "$@"`),
  `oto/cli/` package: `output.py` (TTY/color/width), `errors.py` (exit codes
  + rewrite table shell), `flags.py` (shared
  `--base/--json/-q/-v/--no-input/--no-color` via one
  `add_global_flags(parser)`).
- Fix `render_status.py` argv bootstrap (delete script-mode crash); its
  help example becomes `oto status` — one instance of the "docs must not
  reference nonexistent commands" rule.
- Add `oto --version` from `oto/_version.py` (start at `26.11.0`), `oto help`,
  bare-`oto` orientation screen, dispatcher to subcommands.
- Tests: new `tests/test_cli_smoke.py` (every subcommand: `--help`, bare
  no-arg → exit code 2 or safe orientation, `--json` parses), exit-matrix
  tests; file_length watch (scaffold files <600 lines).

**Phase 2 — command tree by adapters, not rewrites**
- `oto tune` → `oto/runners/cli.py:main` via argparse parent parser
  (flag semantics byte-identical); add `--include-illegal`,
  `--include-underspecified`, `--include-unreproducible`;
  `--no-input` forbids prompts.
- `oto bench`, `oto status`, `oto report`, `oto library *`, `oto check *`,
  `oto verify *`, `oto consolidate`, `oto stats`, `oto chart`,
  `oto docs generate` — each a ~15-line adapter calling the existing
  `main(argv)`; zero logic moved (single-concern commits, one per group).
- Delete root shims (no deprecation, no wrappers — clean break).
- `oto doctor` implemented natively (reuse env/toolchain probe logic
  from `port_tensile --preflight`), with `--fix` hints where safe.

**Phase 3 — output & errors overhaul**
- stdout/stderr contract enforced: narration to stderr; `--json` full
  coverage on read commands; `--quiet`; TTY guards on every color/progress
  emission; `NO_COLOR` honored.
- Error-rewrite: wire table for the top-10 hits (seed from the except-clause
  census and crash sites observed in practice); every driver abort path gains a
  one-line remediation and a documented exit code ≠ 2.
- Help text: rewrite each adapter's epilog with an examples-first block;
  `README.md` command table regenerated from `oto --json help` (test-enforced:
  the example commands must exist).
- UX conformance: all flags have help text (already enforced for the driver by
  `test_interactive_keys`), no dead flags, no command narrate-on-stdout with
  `--json`.

**Phase 4 — docs, migration, polish**
- `docs/README.md` operator section rewritten to `oto <cmd>` vocabulary
  (Class B doc; registry intact); short `docs/cli.md` generated command
  reference registered in the docs registry (`tests/test_docs_registry.py`
  stays green); changelog + `incomplete_work.md` updated.
- `oto completion bash|zsh` behind a flag.
- Final: full suite + `verify_all` (expect the same 4 pre-existing FAILs, no
  new ones); direct user acceptance on the nightly venv.

## 6. Risks & honest tradeoffs

- **No backwards compat**: cron/scripts calling old shims break. Documented
  in `docs/cli.md` migration table, but no aliases provided.
- **Scope**: two projects masquerading as one (GPU pipeline vs dev/refactor
  verifiers) — Phase 2's `oto verify` / `oto check` grouping makes the split
  explicit; deleting either side is a user decision.
- **Effort**: ~4–6 days including tests/docs; phases mean the user can stop
  after any phase with a coherent product.
- **Not in scope**: pipx installable package, Windows support, networked docs,
  deeper `--auto` questionnaire polish (worth doing after Phase 2, small).
- **Verifier caveat**: `verify_*` are frozen ASTs against `6264196`; their
  code is off-limits — adapters only.

## 7. Open questions (decisions required before Phase 1)

1. Command name: `oto` alone (repo-root script) OK? yes
2. How long must legacy shims persist (one release vs indefinite)? — **N/A:
   no legacy shims, clean break.** no shims
3. Name for the new diagnostics command (`oto doctor`)? yes doctor
4. GPU-flag naming: `--include-illegal` on the new surface (no aliasing older
   `--release-*` spellings)? yes include illegal no need to alias older
5. May Phase 1 begin after review, or a narrower first slice (Phase 1 +
   `oto status` only)? full plan approved all phases but ensure you carry it out very carefully so theres no regressions

Nothing is started. Answer the five questions and I'll execute; meanwhile the
plan's component test list is already designed so every phase ends with the
five gate suites green plus the new `test_cli_smoke.py`.

---

**Docs ecosystem update (new nomenclature)**: All Class B (operator) docs in
`docs/` must be updated to use `oto <cmd>` vocabulary instead of
`port_tensile.py --auto` etc. The `docs/README.md` registry must register
any new `*.md` tokens. `claude.md` §1 and root `README.md` §7 routing must
be updated to point at `oto doctor` and `oto status` instead of the old
shims. The generated `docs/cli.md` command reference becomes the single
source of truth for the new nomenclature.

1. oto tune vs oto run
Option A: oto tune = convergence loop only; single-phase work via oto run --stage X Option B: oto tune absorbs everything (convergence + single-phase); --stage selects what to run Option C: oto run is the main command (absorbs --auto and --stage); oto tune is an alias

Recommendation: A — clean separation. oto tune is the 10-hour overnight loop; oto run is "execute these specific phases."

2. --stage routing
Option A: Keep --stage 1..7 or names on oto run (current behavior, minimal change) Option B: Stages become subcommands: oto preflight, oto bench, oto report, etc. Option C: Hybrid: oto run --stage X for execution + oto <stage> as shorthand aliases

Recommendation: B — subcommands are discoverable; --stage is a hidden routing table that nobody memorizes. But this is the biggest surface change.

3. oto doctor scope
Option A: Toolchain only (TENSILE_ROOT, compiler, GPU, .env, venv, Python version) Option B: Toolchain + registry integrity + DB health + doc registry Option C: Toolchain + everything check_db / check_candidates / check_library_parity do

Recommendation: A for Phase 1, then B in Phase 3. Keep oto check db separate for registry-specific diagnostics.

4. --json on every command
Option A: ALL commands support --json Option B: Only read commands (status, stats, report, check, verify) Option C: Only commands that produce structured data (status, stats, report)

Recommendation: B — mutating commands (tune, bench) produce logs, not data; --json on those would be noise.

5. Progress bars
Option A: tqdm if available, custom ANSI fallback Option B: Custom ANSI progress (no external dep) Option C: No progress bars, just line-based output ([3/10] phase_x ...)

Recommendation: C — simplest, works everywhere, no dep, composable with pipes. Add --live for TTY repaint separately.

6. Help style
Option A: argparse built-in with add_argument_group (minimal code) Option B: Custom help formatter with examples-first, bold headings, color Option C: Use rich library for formatted help (external dep)

Recommendation: B — argparse groups handle 90% of it; custom epilog for examples. No external dep.

7. oto invocation
Option A: Repo-root oto shell script (exec python3 -m oto "$@") Option B: python3 -m oto only (no script) Option C: Both (script + module)

Recommendation: A — one command, no typing python3 -m. Script lives at repo root, users add repo root to PATH.

8. Error handling
Option A: Print to stderr + sys.exit(code) (POSIX standard) Option B: Custom exception hierarchy (oto.errors.OtoError) caught by dispatcher Option C: Both — exceptions internally, caught at top level, printed as stderr + exit code

Recommendation: C — clean internally, POSIX externally. Tracebacks saved to logs/oto-<ts>.log for unknown errors.

9. --dry-run
Option A: Available on ALL mutating commands Option B: Available only on oto tune and oto bench Option C: Available on all commands that touch state (tune, bench, consolidate, library best-effort)

Recommendation: C — read commands don't need it; mutating commands that are irreversible get it.

10. --live (TTY repaint)
Option A: Flag on oto tune (current behavior) Option B: Separate oto status --watch command (current render_status behavior) Option C: Both — oto tune --live for inline, oto status --watch for standalone

Recommendation: C — current behavior is fine; just rename --live to --live {on,off}.

11. --generate-device-docs
Option A: oto docs generate [STARTER] Option B: oto agent generate [STARTER] Option C: oto generate docs [STARTER]

Recommendation: A — docs is the noun, generate is the verb. Consistent with oto docs index.

12. Verification scripts
Option A: oto verify all / oto verify run {snapshot,diff,telemetry,cheapest} Option B: oto verify-all / oto verify-run (flat, no subcommands) Option C: Keep as python3 verify_all.py / python3 verify_run.py (no migration)

Recommendation: A — subcommands are discoverable; matches the noun-verb pattern.

13. all_runs.py
Option A: oto stats Option B: oto all_runs Option C: oto report all_runs (nested under report)

Recommendation: A — stats is what it does; all_runs is jargon.

14. check_* scripts
Option A: oto check candidates / oto check db / oto check retirement / oto check library-parity / oto check tensile-build Option B: oto check {candidates,db,retirement,library,build} Option C: Flat: oto check-candidates, oto check-db, etc.

Recommendation: A — noun-verb, consistent with oto verify run.

15. chart.py
Option A: oto chart Option B: oto figures Option C: oto report chart (nested under report)

Recommendation: A — chart is clear enough.

16. consolidate.py
Option A: oto consolidate Option B: oto deck consolidate Option C: oto tools consolidate

Recommendation: A — consolidate is the verb; keep it top-level.

17. port_tensile.py itself
Option A: oto tune (convergence loop) + oto run (single-phase) Option B: oto run (everything) + oto tune (alias for oto run --auto) Option C: oto (bare = run with defaults) + oto run (explicit)

Recommendation: A — tune is the 10-hour loop; run is "execute these phases."

18. Output formatting (colors)
Option A: Colors on TTY by default, --no-color + NO_COLOR to disable Option B: No colors by default, --color to enable Option C: Colors on TTY by default, --color/--no-color to override

Recommendation: A — clig.dev says colors on TTY by default, disable via NO_COLOR/--no-color.

19. --version
Option A: oto version (subcommand) + oto --version (flag) Option B: oto --version flag only Option C: oto version subcommand only

Recommendation: A — both, for discoverability and scriptability.

20. Shell completions
Option A: oto completion bash|zsh (Phase 4) Option B: No completions (Phase 1-3 only) Option C: Completions via external tool (argcomplete)

Recommendation: B for now, A in Phase 4. Not critical for correctness.

21. Config file (oto.toml)
Option A: No config file; .env + env vars + CLI flags only Option B: oto.toml for persistent settings (base_dir, tensile_root, etc.) Option C: Both — .env for secrets, oto.toml for settings

Recommendation: A — .env + env vars + flags is sufficient; adding a config file is scope creep.

22. --no-input
Option A: Implement --no-input on all commands (forbid prompts) Option B: Implement only on oto tune (the only command that prompts) Option C: No --no-input; use --yes for non-interactive

Recommendation: A — clig.dev says every command should support it; --yes is a shortcut, --no-input is the safety net.

23. --quiet
Option A: Implement on all commands Option B: Implement only on read commands (status, stats, report) Option C: No --quiet; use --json for machine output

Recommendation: A — --quiet suppresses narration; --json changes format. Both are useful.

24. --verbose
Option A: Implement on all commands (escalate stderr output) Option B: Implement only on oto tune and oto bench Option C: No --verbose; use --debug instead

Recommendation: A — clig.dev uses --verbose for more output, --quiet for less. Both on all commands.

25. --no-color
Option A: Implement --no-color + NO_COLOR env var on all commands Option B: Implement only NO_COLOR env var (no flag) Option C: No color support at all (plain text only)

Recommendation: A — clig.dev standard; --no-color flag + NO_COLOR env var.


1. agree with your recommendation
2. option b subcommands
3. full doctor impl one shot evergreen
4. option b
5. a, tqdm is fine as a dep no custom in house nonsense
6. use rich. we want to use existing high quality solutions as much as possible instead of developing dinky in house trash
7. explain wtf you mean
8. see how far you can get with posix only, if theres regression minimal custom stuf
9. c, state commands
10. c
11. oto agent generate, all the operator agent stuff should be under oto agent __
12. a 
13. a 
14. a
15. a
16. a
17. a
18. a
19. a
20. do this last, bash and zsh
21. a, no need for toml, env is fine for config + paths + settings + secrets. update env.example if needed ig 
22. a
23. a
24. a
25. colour only, no colour isnt imp