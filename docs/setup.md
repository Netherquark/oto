# Easy-mode onboarding — preparing oto for a new device

> **Class B document.** Read this if you are a human (or an agent) bringing
> oto up on a GPU it has never seen. It is the answer to "what do I run,
> in what order, and what does each step prove?" — the full manual is in
> [`docs/starter_pair.md`](starter_pair.md) (Stage A–D) and
> [`docs/operator_runbook.md`](operator_runbook.md).

## 1. The one-command version

```bash
python3 -m oto setup --yes
```

That runs the whole flow non-interactively with the defaults (blind
convergence, the first complete ROCm SDK it finds, the first Tensile checkout
it finds, gfx90c GPU targets, builds the client, writes `.env`, runs
`oto doctor` and the deck sanity check). If anything is missing it prints the
exact command to fix it and stops.

For a guided walk:

```bash
python3 -m oto setup              # asks each question, accepts defaults
python3 -m oto setup --dry-run    # prints the plan + the .env it would write; no writes
```

## 2. What it asks (and the good defaults)

| Step | Question | Default | Why the default |
|---|---|---|---|
| 1 | Convergence mode — blind or informed? | blind | Most new devices have no reference floor to beat; informed only when a shipped library exists |
| 2 | Spoof (reference floor) GPU codename (informed only) | gfx900 | The shipped floor oto was built against |
| 3 | ROCm install (auto-detected complete SDKs) | first found | Must be a full SDK (see §3) |
| 4 | Tensile checkout (auto-detected) | first found | Must contain `Tensile/bin/Tensile` |
| 5 | GPU targets for the client build | gfx90c | The gfx90c box; re-run for the target arch on the target machine |
| 6 | Build the Tensile client? | yes | CPU-only, 2–5 min, never touches a GPU |
| 7 | Write `.env`? | yes | Never overwrites without `--force` |
| 8 | Verify (doctor + deck sanity) | automatic | Honest status, no fallbacks |

## 3. The full-SDK rule (the thing that bites)

A ROCm install is **usable** only when it ships a **complete HIP include tree**:
`<prefix>/include/hip/amd_detail/amd_warp_functions.h` must exist. A
python-sdk venv (the kind `pip install` produces) ships a *partial* `include/hip`
and the build will silently resolve HIP headers from `/usr` (ROCm 6) and fail
with `__AMDGCN_WAVEFRONT_SIZE` errors. Point `--rocm-prefix` at the full
extracted dist (e.g. the TheRock `dist-<ver>` directory) or `/opt/rocm`.

The setup script enforces this as a hard check and refuses a partial prefix
with an actionable message.

## 4. What "ready" means after setup

`oto doctor` reports 0 FAIL (21 ok / 2 warnings on the reference box — the
warnings are the user's standing advisories: venv-not-active and the abandoned
run from 2026-10-29). Then:

```bash
oto check candidates --quiet          # deck sane
oto agent consult docs/<codename>_starter.md  # CPU-only deck draft
```

Stage A (CPU-only, no key) is complete. Stage B (starter pair + human
verification gate) and Stage D (GPU, TTY) are the next human steps
(`docs/starter_pair.md`).

## 5. Non-interactive / CI usage

```bash
python3 -m oto setup --yes --convergence-mode blind --rocm-prefix /path/to/sdk \
    --tensile-root /path/to/rocm-libraries --gpu-targets gfx90c --skip-build
```

`OTO_NO_INPUT=1` makes every prompt take its default instead of waiting for
stdin; `--dry-run` prints the plan and the `.env` it would write without
touching disk.

## 6. Troubleshooting

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
