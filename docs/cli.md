# oto CLI command reference

Generated from `oto help --json` for oto 1.0.0. Do not hand-edit;
run `oto help --write docs/cli.md` after changing the command tree.

`oto` is the single front door. It is verb-first and noun-scoped: at most
two levels, stdout carries data, stderr carries narration, and read
commands have `--json`.

## Quick start

```bash
oto doctor                     # is this box ready?
oto status                     # what is the current run doing?
oto tune --dry-run             # preview the overnight loop
oto tune --budget 10 --yes     # run it non-interactively
```

The repository-local entry point is `bin/oto`; add `bin/` to `PATH` to
type `oto`. `python3 -m oto` is the same dispatcher.

## Global conventions

- `--base PATH` — project directory (default: current directory).
- `-q/--quiet` — suppress narration; errors still go to stderr.
- `-v/--verbose` — show the command line and full tracebacks.
- `--no-input` — never prompt; take documented defaults or fail.
- `--no-color` / `NO_COLOR` — disable ANSI colour.
- `--json` — read commands only: one JSON document on stdout.
- `-n/--dry-run` — state-changing commands: print the plan, change nothing.
- Exit codes: `0` ok, `1` failure, `2` usage error, `130` interrupted.

## Commands

### `oto agent`

Operator-agent operations

```bash
oto agent generate docs/starter.md
oto agent index
```

#### `oto agent consult`

Draft <codename>_potential_configs.md (CPU-only census consult)

```bash
oto agent consult docs/operator/gfx902_starter.md
oto agent consult --out my_device.md
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--out` — Output path (default: <codename>_potential_configs.md in base dir)
- `--force` — Overwrite an existing output file
- `--with-docs` — Also generate the agent-1/agent-2 device docs beside the consult output

#### `oto agent generate`

Generate device docs (agent-1 + agent-2)

```bash
oto agent generate docs/operator/gfx902_starter.md --dry-run
oto agent generate docs/operator/gfx902_starter.md
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `-n`, `--dry-run` — Show what would happen without executing

#### `oto agent index`

Regenerate docs/docs_index.json

```bash
oto agent index
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)

### `oto analytics`

the analytics stage: analytics summary for a run

```bash
oto analytics
oto analytics --stage 5
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--tensile-root` — 
- `--json` — Emit one JSON document on stdout; silence narration

### `oto bench`

Benchmark the reference floor, native loop, or a scope

```bash
oto bench --dry-run                  # list matched manifest targets
oto bench --native --limit 5         # native-only smoke test
oto bench --family SS --shape 1024x1024x1024
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--native` — Native-only loop (no gfx900 reference floor)
- `--limit` — Max reference phases (one per family)
- `--ref-shapes` — Comma-separated cube sides, e.g. 256,512
- `--resume` — Resume the reference floor
- `--refresh` — Re-scan the system dat
- `--targets` — Target IDs or labels
- `--family` — Family labels (e.g. SS or CC DD)
- `--pattern` — Contraction patterns
- `--shape` — Problem shapes
- `-n`, `--dry-run` — Show what would happen without executing
- `--force` — Run even when an identical fingerprint already passed
- `--live` {on,off} (default: `on`) — Live TTY status panel (default: on)
- `--live-interval` (default: `30.0`) — Seconds between live status repaints (default: 30)
- `--tensile-root` — Override TENSILE_ROOT for this command

### `oto candidate`

the candidate stage: print the candidate plan by family

```bash
oto candidate
oto candidate --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--tensile-root` — 
- `--json` — Emit one JSON document on stdout; silence narration

### `oto chart`

Generate the native-vs-floor comparison figure

```bash
oto chart
oto chart --out my_chart.png
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--out` — Output PNG path

### `oto check`

Diagnostic assertions (read-only)

```bash
oto check candidates --quiet
oto check db --json
```

#### `oto check candidates`

Deck linter: four-gate legality

```bash
oto check candidates --quiet
oto check candidates --deck phases.yaml --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--deck` — Deck or overlay YAML (default: phases.yaml)
- `--family` — Only this family label
- `--floor` — Sweep the shipped gfx900 floor manifest
- `--json` — Emit one JSON document on stdout; silence narration

#### `oto check db`

Registry integrity and label contamination

```bash
oto check db
oto check db --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--json` — Emit one JSON document on stdout; silence narration

#### `oto check library-parity`

Coverage parity vs the shipped gfx900 grid

```bash
oto check library-parity --quiet
oto check library-parity --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--phases` — Explicit deck file; implies no overlays
- `--overlay` — Extra overlay YAML(s)
- `--run-id` — Fold in this run's overlay
- `--no-seed` — Skip the seed overlay
- `--json` — Emit one JSON document on stdout; silence narration

#### `oto check retirement`

Retirement records and per-cell samples

```bash
oto check retirement
oto check retirement --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--json` — Emit one JSON document on stdout; silence narration

#### `oto check tensile-build`

CPU-only Tensile build proof

```bash
oto check tensile-build --family ZZ --jobs 8
oto check tensile-build --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--family` — Only this FamilyLabel
- `--phase-id` — Only this phase id
- `--arch` — Tensile arch (default: profile codename)
- `--timeout` (default: `600`) — Seconds per phase
- `--jobs` (default: `1`) — Parallel phases
- `--compare` — Cross-check oto's occupancy model against Tensile
- `--keep` — Keep build artifacts here
- `--json` — Emit one JSON document on stdout; silence narration

### `oto completion`

Generate shell completions

```bash
oto completion bash
oto completion zsh > _oto
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)

### `oto consolidate`

Consolidate the floor into a locked deck

```bash
oto consolidate --dry-run        # stage only (default)
oto consolidate --commit         # install after parity passes
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--commit` — Install the consolidated deck (default: stage only)
- `--explain-archive` — Explain which runs the archive keeps
- `-n`, `--dry-run` — Show what would happen without executing

### `oto doctor`

Diagnose the toolchain, GPU, registry, and docs

```bash
oto doctor                       # human checklist with hints
oto doctor --json                # machine-readable verdict
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--json` — Emit one JSON document on stdout; silence narration

### `oto help`

Show help for a topic

```bash
oto help
oto help tune
oto help --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--json` — Emit one JSON document on stdout; silence narration
- `--write` — Regenerate the Markdown command reference

### `oto library`

Tensile library operations

```bash
oto library best-effort
oto library best-effort --protocol-basis any
```

#### `oto library best-effort`

Carve the best-effort .dat (CPU-only)

```bash
oto library best-effort --dry-run
oto library best-effort --dest out/ --protocol-basis any
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--dest` — Destination directory
- `--protocol-basis` {family,any,single,partial} — Protocol basis for carving (default: 'any', the across-all-runs view)
- `-n`, `--dry-run` — Show what would happen without executing

### `oto preflight`

the preflight stage: validate the run environment

```bash
oto preflight
oto preflight --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--tensile-root` — 
- `--json` — Emit one JSON document on stdout; silence narration

### `oto report`

Regenerate the acceptance report

```bash
oto report                       # newest native run
oto report --run <id> --json     # machine-readable payload
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--run` — run_id to report on (default: newest)
- `--json` — Emit one JSON document on stdout; silence narration

### `oto retirement`

the retirement stage: retire stable cells (registry-only)

```bash
oto retirement --dry-run
oto retirement
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--tensile-root` — 
- `-n`, `--dry-run` — Show what would happen without executing

### `oto run`

Execute an explicit multi-stage selection

```bash
oto run --stage preflight candidate   # two stages, one process
oto run --stage benchmark --family SS --dry-run
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--stage` (default: `[]`) — preflight, candidate, benchmark, retirement, analytics, synthesis, report
- `--targets` — Target IDs or labels
- `--family` — Family labels (e.g. SS or CC DD)
- `--pattern` — Contraction patterns
- `--shape` — Problem shapes
- `-n`, `--dry-run` — Show what would happen without executing
- `--force` — Run even when an identical fingerprint already passed
- `--live` {on,off} (default: `on`) — Live TTY status panel (default: on)
- `--live-interval` (default: `30.0`) — Seconds between live status repaints (default: 30)
- `--tensile-root` — Override TENSILE_ROOT for this command

### `oto setup`

Easy-mode onboarding: prepare oto for a new device

```bash
oto setup
oto setup --yes --convergence-mode blind
oto setup --dry-run
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--yes`, `-y` — Non-interactive: take defaults, never prompt
- `--dry-run` — Print the plan and the .env it would write; no writes
- `--force` — Overwrite an existing .env
- `--convergence-mode` {blind,informed} — Convergence mode (default: blind)
- `--spoof` — Spoof (reference floor) GPU codename (informed mode)
- `--rocm-prefix` — ROCM install prefix (auto-detected if omitted)
- `--tensile-root` — Tensile checkout root (auto-detected if omitted)
- `--download-rocm` {python,dnf,none} — Install a nightly TheRock SDK into --rocm-venv (python) or print dnf commands (dnf). Default: none; without this flag and without --yes, the wizard asks.
- `--rocm-venv` (default: `~/.local/share/oto/rocm-nightly-venv`) — Where the nightly wheel venv is created (default: ~/.local/share/oto/rocm-nightly-venv)
- `--download-torch` — Also install torch/torchvision/torchaudio nightly wheels for --rocm-venv (large download)
- `--download-tensile` {clone,none} — Sparse-clone ROCm/rocm-libraries (shared/tensile) into --tensile-dest. Default: none; without this flag and without --yes, the wizard asks.
- `--tensile-dest` (default: `~/.local/share/oto/rocm-libraries`) — Where ROCm/rocm-libraries is sparse-cloned (default: ~/.local/share/oto/rocm-libraries)
- `--gpu-targets` — GPU targets for the client build (comma list)
- `--jobs` (default: `4`) — Parallel build jobs
- `--skip-build` — Do not build the Tensile client
- `--build-client` (default: `True`) — Build the Tensile client if missing (default: on)
- `--write-env` — Write the .env file (default: ask)
- `--codename` (default: `gfx90c`) — Target codename written into .env hints (default: gfx90c)

### `oto stats`

Cross-run best config per cell

```bash
oto stats
oto stats --family ZZ --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--family` — Filter to one family label
- `--json` — Emit one JSON document on stdout; silence narration

### `oto status`

Show run status, ETA, and the live panel

```bash
oto status                      # one-shot report
oto status --watch 30           # refresh every 30 seconds
oto status --thermals --json    # machine-readable with thermals
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--watch` — Refresh every N seconds
- `--thermals` — Include thermals
- `--plan` (default: `[]`) — Project a plan (rerun_illegal=no, iterations=4, ...)
- `--run` — run_id to report on (default: newest)
- `--json` — Emit one JSON document on stdout; silence narration

### `oto synthesis`

the synthesis/build stage: build and validate the native library

```bash
oto synthesis --dry-run
oto synthesis
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--tensile-root` — 
- `-n`, `--dry-run` — Show what would happen without executing

### `oto tune`

Run the convergence loop (the overnight job)

```bash
oto tune --dry-run                  # list the plan, no GPU work
oto tune --budget 10 --yes          # accept defaults, no prompts
oto tune --include-illegal --resume # re-measure the illegal tier
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--budget` — Convergence iterations
- `--mutations` — Max mutations per candidate
- `--resume` — Resume the reference floor where it stopped
- `--include-illegal` — (no-op; the reference floor always re-measures the illegal tier)
- `--include-underspecified` — Re-measure the UNDER-SPECIFIED reference cells
- `--include-unreproducible` — Re-attempt the UNREPRODUCIBLE reference cells
- `-y`, `--yes` — Accept the default plan without prompting
- `--live` {on,off} (default: `on`) — Live TTY status panel (default: on)
- `--live-interval` (default: `30.0`) — 
- `--tensile-root` — Override TENSILE_ROOT for this run
- `-n`, `--dry-run` — Show what would happen without executing

### `oto verify`

Verification commands

```bash
oto verify all
oto verify run snapshot --out before.json
```

#### `oto verify all`

Run all equivalence verifiers

```bash
oto verify all
oto verify all --base-ref 2824c2f
oto verify all --json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--base-ref` — Ref to compare against (default: HEAD~1, the evergreen per-commit base; pass a specific ref for the legacy comparison)
- `--json` — Emit one JSON document on stdout; silence narration

#### `oto verify run`

Corpus snapshot/diff/telemetry

```bash
oto verify run snapshot --out before.json
oto verify run diff before.json after.json
oto verify run telemetry <run_id>
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--json` — Emit one JSON document on stdout; silence narration

##### `oto verify run cheapest`

Cheapest legal phases for a smoke run

```bash
oto verify run cheapest --family ZZ --n 3
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--family` — Dtype char filter, e.g. ZZ
- `--n` (default: `5`) — Number of phases
- `--json` — Emit one JSON document on stdout; silence narration

##### `oto verify run diff`

Compare two snapshots; non-zero on data loss

```bash
oto verify run diff before.json after.json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--json` — Emit one JSON document on stdout; silence narration

##### `oto verify run snapshot`

Record corpus state as JSON

```bash
oto verify run snapshot --out before.json
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--out` — Write JSON here instead of stdout
- `--json` — Emit one JSON document on stdout; silence narration

##### `oto verify run telemetry`

Per-phase telemetry funnel for one run

```bash
oto verify run telemetry <run_id>
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)
- `--json` — Emit one JSON document on stdout; silence narration

### `oto version`

Print the version

```bash
oto version
```

Flags:

- `--base` — Project base directory (default: current directory)
- `-q`, `--quiet` — Suppress narration; errors still go to stderr
- `-v`, `--verbose` — Show the command being run and full tracebacks on failure
- `--no-input` — Never prompt; take documented defaults or fail
- `--no-color` — Disable ANSI colour (also honours NO_COLOR)

## Migration from the old scripts

There are no compatibility shims and no aliases. This is the clean break.

| Old command | New command |
|---|---|
| `python3 port_tensile.py --auto` | `oto tune` |
| `python3 port_tensile.py --auto --budget 10 --yes` | `oto tune --budget 10 --yes` |
| `python3 port_tensile.py --preflight` | `oto preflight  (or oto doctor)` |
| `python3 port_tensile.py --report` | `oto report` |
| `python3 port_tensile.py --best-library` | `oto library best-effort` |
| `python3 port_tensile.py --generate-device-docs` | `oto agent generate` |
| `python3 port_tensile.py --gfx900-reference` | `oto bench` |
| `python3 port_tensile.py --native` | `oto bench --native` |
| `python3 all_runs.py` | `oto stats` |
| `python3 check_candidates.py` | `oto check candidates` |
| `python3 check_db.py` | `oto check db` |
| `python3 check_retirement.py` | `oto check retirement` |
| `python3 check_library_parity.py` | `oto check library-parity` |
| `python3 check_tensile_build.py` | `oto check tensile-build` |
| `python3 consolidate.py` | `oto consolidate` |
| `python3 chart.py` | `oto chart` |
| `python3 verify_all.py` | `oto verify all` |
| `python3 corpus_audit.py snapshot` | `oto verify run snapshot` |
| `python3 -m oto.metrics.render_status` | `oto status` |
