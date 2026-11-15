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
| 2 | Spoof (reference floor) GPU codename (informed only) | gfx900 | The shipped floor oto was built against; the community-popular spoof |
| 3 | ROCm flavour — python (TheRock venv) or opt (`/opt/rocm*`) | python | Must be a *full* SDK (see §3); python SDK is the tested path |
| 4 | ROCm version policy — nightly or pinned | nightly | Nightly is what gfx90c was measured against; pin only to reproduce a prior run |
| 5 | Pinned ROCm version (if pinned) | 7.15.0a20260728 | Recorded in `.env`; never re-derived |
| 6 | Tensile version policy — nightly or pinned | pinned | The gfx902 bookkeeping landed at a specific rocm-libraries commit |
| 7 | Pinned Tensile commit/SHA (if pinned) | (current checkout) | Recorded in `.env`; never re-derived |
| 8 | HIP/clang version | (from SDK) | Taken from the chosen SDK's `amdclang++ --version` |
| 9 | ROCm install (auto-detected complete SDKs) | first found | Must be a full SDK (see §3) |
| 10 | Tensile checkout (auto-detected) | first found | Must contain `Tensile/bin/Tensile` |
| 11 | GPU targets for the client build | gfx90c | The gfx90c box; re-run with `gfx902` on the target machine |
| 12 | Build the Tensile client? | yes | CPU-only, 2–5 min, never touches a GPU |
| 13 | Write `.env`? | yes | Never overwrites without `--force` |
| 14 | Verify (doctor + deck sanity) | automatic | Honest status, no fallbacks |

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

See [`docs/toolchain_client.md`](toolchain_client.md) (troubleshooting section).
