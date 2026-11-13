# oto CLI command reference

Generated command reference for the `oto` dispatcher. Run `oto <cmd> --help`
for full flag details.

## Quick start

```bash
python3 oto.py doctor          # diagnose environment
python3 oto.py status          # run status and ETA
python3 oto.py tune --dry-run  # preview convergence loop
python3 oto.py tune --budget 10 --yes  # run convergence loop
```

## Commands

### `oto` (bare)
Prints orientation screen with quick-start commands.

### `oto tune`
Run the convergence loop (auto-convergence across all shipped families).

```bash
python3 oto.py tune --dry-run              # preview without executing
python3 oto.py tune --budget 10 --yes      # accept default plan, no prompts
python3 oto.py tune --resume               # continue from latest run
python3 oto.py tune --include-illegal      # re-measure illegal reference cells
python3 oto.py tune --live off             # quiet transcript
```

Flags: `--budget`, `--mutations`, `--resume`, `--include-illegal`,
`--include-underspecified`, `--include-unreproducible`, `--yes`, `--live {on,off}`

### `oto run`
Run specific pipeline stages.

```bash
python3 oto.py run --stage preflight       # run preflight only
python3 oto.py run --stage candidate --family SS  # run candidate stage for SS
python3 oto.py run --dry-run               # list matched targets
```

Flags: `--stage`, `--targets`, `--family`, `--pattern`, `--shape`,
`--dry-run`, `--force`

### `oto bench`
Benchmark phases.

```bash
python3 oto.py bench --dry-run             # list matched targets
python3 oto.py bench --native --limit 5    # native-only smoke test
python3 oto.py bench --family SS --shape 1024x1024x1024
```

Flags: `--native`, `--limit`, `--ref-shapes`, `--resume`, `--refresh`,
`--targets`, `--family`, `--pattern`, `--shape`, `--dry-run`

### `oto status`
Run status, ETA, and live panel.

```bash
python3 oto.py status                      # one-shot report
python3 oto.py status --watch 30           # refresh every 30s
python3 oto.py status --thermals --json    # machine-readable with thermals
```

Flags: `--watch`, `--thermals`, `--plan`, `--run`, `--json`

### `oto report`
Regenerate acceptance report.

```bash
python3 oto.py report                      # latest run
python3 oto.py report --run <run_id> --json
```

Flags: `--run`, `--json`

### `oto doctor`
Diagnose environment (toolchain, GPU, registry).

```bash
python3 oto.py doctor                      # full diagnostic
python3 oto.py doctor --json               # machine-readable
```

### `oto verify all`
Run all refactor verifiers.

```bash
python3 oto.py verify all
```

### `oto verify run`
Corpus snapshot/diff/telemetry.

```bash
python3 oto.py verify run snapshot --out before.json
python3 oto.py verify run diff before.json after.json
python3 oto.py verify run telemetry run_20261005_170141
python3 oto.py verify run cheapest --family ZZ
```

### `oto check candidates`
Deck linter.

```bash
python3 oto.py check candidates --quiet
python3 oto.py check candidates --deck gfx90c_results/overlays/phases.seed.overlay.yaml --quiet
```

### `oto check db`
Registry integrity.

```bash
python3 oto.py check db
```

### `oto check retirement`
Retirement assertion.

```bash
python3 oto.py check retirement
```

### `oto check library-parity`
Coverage parity vs shipped gfx900.

```bash
python3 oto.py check library-parity
```

### `oto library best-effort`
Carve best-effort .dat (CPU-only).

```bash
python3 oto.py library best-effort
python3 oto.py library best-effort --dest gfx90c_results/best_effort_library --protocol-basis family
```

Flags: `--dest`, `--protocol-basis {family,any,single,partial}`, `--dry-run`

### `oto library verify`
Coverage parity check.

```bash
python3 oto.py library verify
```

### `oto library build-proof`
Build-proof assertion.

```bash
python3 oto.py library build-proof
```

### `oto consolidate`
Deck consolidation.

```bash
python3 oto.py consolidate
```

### `oto stats`
Cross-run best config per cell.

```bash
python3 oto.py stats
python3 oto.py stats --family ZZ --json
```

Flags: `--family`, `--json`

### `oto chart`
Generate comparison figures.

```bash
python3 oto.py chart
```

### `oto agent generate`
Generate device docs (agent-1/agent-2).

```bash
python3 oto.py agent generate docs/<codename>_starter.md
```

### `oto agent index`
Regenerate docs index.

```bash
python3 oto.py agent index
```

### `oto version`
Print version.

```bash
python3 oto.py version
python3 oto.py --version
```

### `oto help`
Show help for a topic.

```bash
python3 oto.py help
python3 oto.py help tune
```

### `oto completion`
Generate shell completions.

```bash
python3 oto.py completion bash
python3 oto.py completion zsh
```

To install bash completions:
```bash
python3 oto.py completion bash >> ~/.bashrc
```

To install zsh completions:
```bash
python3 oto.py completion zsh > ~/.zsh/completions/_oto
```

## Global flags

Available on all commands:
- `--base`, `--base-dir` — base directory (default: cwd)
- `-q`, `--quiet` — suppress non-essential output
- `-v`, `--verbose` — verbose stderr output
- `--no-input` — never prompt
- `--json` — machine-readable JSON output (read commands only)
- `--dry-run` — show what would happen without executing (state commands only)

## Environment variables

- `TENSILE_ROOT` — Tensile source tree root
- `ROCM_PATH` — ROCm installation path
- `OTO_API_KEY` — API key for agent research
- `NO_COLOR` — disable color output
- `OTO_YES` — accept default plan without prompting (CI)

## Migration from old commands

| Old command | New command |
|---|---|
| `python3 port_tensile.py --auto` | `python3 oto.py tune` |
| `python3 port_tensile.py --auto --budget 10 --yes` | `python3 oto.py tune --budget 10 --yes` |
| `python3 port_tensile.py --preflight` | `python3 oto.py doctor` |
| `python3 port_tensile.py --report` | `python3 oto.py report` |
| `python3 port_tensile.py --best-library` | `python3 oto.py library best-effort` |
| `python3 port_tensile.py --generate-device-docs` | `python3 oto.py agent generate` |
| `python3 port_tensile.py --native` | `python3 oto.py bench --native` |
| `python3 port_tensile.py --gfx900-reference` | `python3 oto.py bench --limit N --ref-shapes ...` |
| `python3 allruns.py` | `python3 oto.py stats` |
| `python3 check_candidates.py --quiet` | `python3 oto.py check candidates --quiet` |
| `python3 check_db.py` | `python3 oto.py check db` |
| `python3 check_retirement.py` | `python3 oto.py check retirement` |
| `python3 check_library_parity.py` | `python3 oto.py check library-parity` |
| `python3 check_tensile_build.py` | `python3 oto.py check tensile-build` |
| `python3 consolidate.py` | `python3 oto.py consolidate` |
| `python3 chart.py` | `python3 oto.py chart` |
| `python3 verify_all.py` | `python3 oto.py verify all` |
| `python3 verify_run.py snapshot` | `python3 oto.py verify run snapshot` |
| `python3 -m oto.metrics.render_status` | `python3 oto.py status` |
