# Toolchain & client — how oto finds ROCm and builds `tensile-client`

> Whoever fills this out is not guessing: there is exactly one resolver, one
> contract, and one build script. A toolchain problem is a real problem with a
> real answer.

## 1. Toolchain resolution contract (`oto/runners/toolchain.py`)

**No fallbacks exist.** Guessing a ROCm produces a corpus that measures the
wrong toolchain, so every path is explicit:

| What | Where set | Precedence (highest first) |
|---|---|---|
| `TENSILE_ROOT` (checkout root for Tensile) | flag / env / `.env` | `--tensile-root` > live env > repo-root `.env` |
| `ROCM_PATH` (the ROCm install) | env / `.env` only | live env > `.env` (no flag, by design) |
| `HIP_PATH`, `ROCM_BIN`, `ROCM_LLVM_BIN` | env / `.env` | explicit env wins; derived from `ROCM_PATH` when unset |
| `TENSILE_ASSEMBLER` | env / `.env` | explicit env wins; derived from the SDK's `amdclang++` when unset |
| `ROCM_VERSION`, `HIP_DEVICE_LIB_PATH` | env / `.env` | explicit env wins; documented defaults in `.env.example` |

The `.env` lives at the repo root. It is deliberately never committed.
`python-dotenv` loads it once at `oto.runners.toolchain` import time.

The resolver **understands three ROCm layouts** (no `/usr` guessing):

| Layout | Where `amdclang++` lives | Where `amd_smi` lives |
|---|---|---|
| TheRock tarball / extracted dist (`dist-<ver>`) | `<prefix>/lib/llvm/bin` | `<prefix>/lib/cmake/amd_smi` |
| TheRock Python-sdk venv | `<prefix>/lib/python*/site-packages/_rocm_sdk_core/lib/llvm/bin` | `<venv>/\_rocm_sdk_core/lib/cmake/amd_smi` |
| RPM/tarball (`/opt/rocm*`, `/usr`) | `<prefix>/lib64/rocm/llvm/bin` | `<prefix>/lib/cmake/amd_smi` (absent on older ROCm — see §4) |

`hipconfig` is no longer consulted for resolution (it stays as an optional
cross-check); `ROCM_PATH` set in the environment is the single answer a Port
owner has to give.

## 2. `OTO_TENSILE_CLIENT` — when the client is not at the usual place

`oto doctor` probes `${TENSILE_ROOT}/build/client/tensile-client` by default.
Export `OTO_TENSILE_CLIENT=/absolute/path/to/tensile-client` to override it —
the same rule as everywhere: explicit > env, nothing guessed.

## 3. Building the benchmark client (CPU-only)

`Tensile` does not build the benchmark client anymore; the client lives in
`next-cmake` and must be compiled once per machine. Compilation is CPU-only;
nothing here touches a GPU.

```bash
scripts/build_tensile_client.sh --rocm-prefix /path/to/rocm-dist \
        --tensile-root /path/to/rocm-libraries
```

The script does everything, in order, and fails fast with the exact reason:

1. **Full-SDK marker** — requires `<prefix>/include/hip/amd_detail/amd_warp_functions.h`.
   A python-sdk venv ships a *partial* `include/hip` — the build would resolve
   HIP headers from `/usr` and mix ROCm 6/`/usr/include` headers against the
   nightly clang (`__AMDGCN_WAVEFRONT_SIZE` errors). Use the full extracted
   dist (`dist-<ver>`) prefix instead, as the gfx90c box does.
2. **Compiler detection** — `amdclang`/`clang-19`/`clang`/`hipcc` for C,
   `amdclang++`/`clang++`/`hipcc` for C++, searched only under the prefix:
   `lib/llvm/bin`, `llvm/bin`, the python-sdk layout, `lib64/rocm/llvm/bin`,
   then `<prefix>/bin`. No `/usr` fallback — an empty result is an error,
   not a wrong-cache compiler.
3. **amd_smi** — required by the client. Auto-detected under the prefix;
   pass `--amd-smi-dir` otherwise. If the prefix has no amd_smi (ROCm 6.4.x),
   the client cannot be built for this box — that is a fact, and the error
   says so.
4. **cmake ≥ 3.21.2** (next-cmake requirement), `CMAKE_BUILD_TYPE=Release`,
   `GPU_TARGETS` from `--targets` (default `gfx90c`).
5. Build, verify `--version` (no GPU is touched), install to
   `<TENSILE_ROOT>/build/client/tensile-client` (where `oto doctor` probes).

`--dry-run` prints the exact configure/build line instead of executing.
`--jobs N` sets parallelism. `--targets` sets `GPU_TARGETS`.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `__AMDGCN_WAVEFRONT_SIZE` undeclared | ROCm 6 HIP header shadowing the nightly SDK | use the full dist prefix |
| `amd_smi cmake config not found` | prefix has no amd_smi | use a ROCm 7.x SDK prefix or pass `--amd-smi-dir` |
| `amdclang(++) not found` | wrong prefix layout | let the script detect; see §1 table |
| `cmake version < 3.21.2` | old cmake | upgrade cmake |
| device libraries fail (`rocblas/Logic` absent) | partial rocm-libraries checkout | irrelevant for the client; the device-library step only matters for the full library build |

## 4. When the prefix is incomplete

ROCm 6.4.x does not ship `amd_smi`, so the current client cannot be built
against it. This is a toolchain constraint, not a bug: the fix is a ROCm 7.x
SDK prefix (the one the nightly boxes use), never a franken-prefix of mixed
versions.

## 5. The `oto` side of the fence

`oto doctor` reports every row honestly: toolchain (incl. the client), GPU,
device profile, registry health, corpus coverage, docs registry, index. Zero
FAILs is the bar, and it's what this repo's docs assert.

`OTO_TENSILE_CLIENT=/path/to/tensile-client` bypasses the probe location.

## See also

`docs/operator_runbook.md` — the operator SOP; `docs/search_philosophy.md`;
`.env.example` — the layout reference for each key.


## Troubleshooting (from setup.md)



See `docs/toolchain_client.md` for the toolchain contract and the client-build
troubleshooting table. The most common failure modes:

- `No complete ROCm SDK found` → install TheRock nightly or pass
  `--rocm-prefix`.
- `amd_smi cmake config not found` → the prefix has no amd_smi (ROCm 6.4.x);
  use a 7.x SDK.
- `amdclang(++) not found` → check the prefix's layout; the script searches
  `lib/llvm/bin`, `llvm/bin`, the python-sdk layout, `lib64/rocm/llvm/bin`,
  then `<prefix>/bin`.
- Client build fails on `__AMDGCN_WAVEFRONT_SIZE` → partial-SDK shadowing
  (§3 above).
- `oto doctor` still reports FAIL after a successful build → the binary is at
  `<TENSILE_ROOT>/build/client/tensile-client`; if `TENSILE_ROOT` changed,
  pass `OTO_TENSILE_CLIENT=/path/to/tensile-client`.

## 7. What this does not do

- Does not download anything. Downloads are deliberate (1.6 GB tarballs,
  nightly snapshots) and the script prints the exact command instead of
  running it.
- Does not modify `oto/`, `tests/`, or root shims. It writes `profiles/*`,
  `docs/*_starter.*`, generated device docs, run artifacts, and (with
  consent) `.env`.
- Does not run the GPU. Every step is CPU-only.
- Does not invent silicon facts. The starter pair refuses unverified profiles.
