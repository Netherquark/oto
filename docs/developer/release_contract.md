# oto v1.0.0 — stability contract
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


What a `1.0.0` tag commits to. Anything not listed here may change in a minor
release without notice. This is the audit you asked for; it is intentionally
exhaustive about the *machine-facing* surface, not about prose.

## How to re-verify this contract

```bash
python3 -m pytest -q            # the suite (guard rails + contract tests below)
python3 -m oto verify all       # evergreen equivalence checks
python3 -m oto doctor           # expect 0 FAIL
```

`verify all` checks equivalence at `HEAD~1`; the JSON/artifact formats below are
checked by their own tests and by `oto check db`.

## Contracted surface

### CLI command tree

Stable at `1.0.0`; removed commands are a major bump, additive command groups are minor.

| Group | Children | Kind |
|---|---|---|
| `oto tune` | — | mutating |
| `oto run` | — | mutating |
| `oto bench` | — | mutating |
| `oto status` | — | read |
| `oto report` | — | read |
| `oto doctor` | — | read |
| `oto preflight` | — | read |
| `oto candidate` | — | read |
| `oto retirement` | — | mutating |
| `oto analytics` | — | read |
| `oto synthesis` | — | mutating |
| `oto verify` | `all`; `run` → `snapshot`, `diff`, `telemetry`, `cheapest` | read |
| `oto check` | `candidates`, `db`, `library-parity`, `retirement`, `tensile-build` | read |
| `oto library` | `best-effort` | mutating |
| `oto agent` | `consult`, `generate`, `index` | read/special |
| `oto setup` | — | mutating |
| `oto consolidate` | — | mutating |
| `oto stats` | — | read |
| `oto chart` | — | read |
| `oto version` | — | read |
| `oto help`, `oto completion` | — | read/special |

Global flags, everywhere they are accepted: `--base`, `-q/--quiet`,
`-v/--verbose`, `--no-input`, `--no-color`, `--json`. `oto tune`/`oto run` add
their run flags; `oto setup` adds its own (`--yes`, `--dry-run`,
`--convergence-mode`, `--rocm-prefix`, `--tensile-root`, `--download-rocm`,
`--download-torch`, `--download-tensile`, `--rocm-venv`, `--tensile-dest`,
`--gpu-targets`, `--jobs`, `--skip-build`, `--build-client`, `--write-env`,
`--codename`, `--force`).

### Exit codes

- `0` — success (including a dry-run plan).
- `1` — failure (known OtoError with a remediation hint, or unknown — writes a
  traceback to `logs/`).
- `2` — usage error (argparse/POSIX-style).
- `130` — interrupted (`KeyboardInterrupt`).

`oto setup` without a TTY and without `--yes`/`--dry-run` exits `2` with a
stderr hint, never a traceback.

### stdout / stderr policy

- Data (machine payloads, file paths being reported, `version`) → **stdout**.
- Narration (banners, discovery, progress, profiler text) → **stderr**, never
  stdout. Mutating commands redirect backend narration to stderr.
- `--quiet` sends narration to `/dev/null`; errors still go to stderr.
- `--no-color` or `NO_COLOR=1` disables colour.
- `--json` swaps a read command's output for a machine payload on stdout;
  on failure it prints `{"ok": false, "error": {code, message, hint, command,
  [traceback]}}`.

### Machine-readable artifacts (additive evolution only)

| Artifact | Contract |
|---|---|
| `gfx90c_results/acceptance_report.json` | Top-level keys in `acceptance_report.json` for a completed run: `execution_timing`, `family_timing`, `native_arm`, `orange_list`, `overall_pass`, `per_cell_verdicts`, `per_family_coverage`, `protocol_fallback`, `red_list`, `reference_run_id`, `run_id`, `shipped_manifest`, `summary`, `timestamp`. Field types are stable; keys may only be **added** in minor releases. |
| `docs/docs_index.json` | Keys: `agent_classes`, `documents`, `generated_from`, `total`, `version`. Additive only. |
| `oto/tools/verifiers/drift_manifest.json` | `{ "ast_equivalence": [ { "key": str, "reason": str }, … ] }` where `key` is `<file>::<func>`; unknown keys are fatal for the verifier (by design). |
| `gfx90c_results/registry.db` | SQLite, append-only. Tables: `runs`, `phases`, `proposals`, `proposal_observations`, `records`. Columns are additive; readers must tolerate unknown columns/tables. Never rewritten by oto tooling. |
| `oto phases.yaml` (deck schema) | Row keys are consumed by the deck check and gates; schema evolves additively — deck *content* is not contracted. |

### Environment / .env contract

`TENSILE_ROOT`, `ROCM_PATH`, `HIP_PATH`, `ROCM_BIN`, `ROCM_LLVM_BIN`,
`TENSILE_ASSEMBLER`, `TENSILE_ASSEMBLER_FALLBACK`, `HIP_DEVICE_LIB_PATH`,
`ROCM_DEVICE_LIB_PATH`, `ROCM_VERSION`, `OTO_TENSILE_CLIENT` (overrides the
client autodetect), plus `OTO_QUIET`, `OTO_VERBOSE`, `OTO_NO_INPUT`, `OTO_YES`,
`NO_COLOR`. `ROCBLAS_TENSILE_LIBPATH` is honoured by human-facing examples
(e.g. yolo26), not by oto itself. `MIOPEN_*` variables are yolo26's, not oto's.

### Version surface

- `oto --version` / `oto version` print `oto <x.y.z>` (SemVer from `pyproject.toml`).
- The `total` count in `docs_index.json` tracks the registered document count.

## Not contracted

- Python module internals, class/mixin names, and import layout (refactors land
  in minors; that is what majors are for).
- All numeric verdicts (GFLOP/s, medians, mismatches), deck contents, gate
  thresholds, and doc prose.
- `phases.yaml` contents; retirement decisions; invariants as *content* (they
  are policy, not API).
- Anything marked `UNVERIFIED` in the docs.
- Rendering (HTML/CSS/report colours), exact wording of hints and tracebacks,
  and the `logs/` traceback file format.

## Release policy

- MAJOR: removes/renames a contracted command, flag, exit code, JSON key, or
  table. One minor release of deprecation notice comes first.
- MINOR: additive command groups, flags, JSON keys, tables.
- PATCH: bug fixes without observable surface change. `1.0.0` is the first
  release under this policy; the deprecation-notice rule starts at `1.1.0`.
