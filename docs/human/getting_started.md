# Getting started with oto

> **Ecosystem: Human.** Agents pick their class first — operators read
> [`docs/operator/operator_runbook.md`](../operator/operator_runbook.md), developers read
> [`AGENTS.md`](../../AGENTS.md).
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d

The full guide to bringing oto up on a box. For the birds-eye view, see
[`docs/overview.md`](../overview.md). For the philosophy, see [`README.md`](../README.md).

## 1. Prerequisites

- Linux (Fedora / RHEL / Ubuntu tested), Python ≥ 3.10. Any modern
  distribution with a working ROCm toolchain is expected to work.
- An AMD GPU oto has never seen (gfx90c, gfx902, …).
- A ROCm 7.x install (TheRock nightly recommended) — Python SDK venv or
  extracted tarball. **Never** the ROCm 6.4.x system install; the nightly is
  what the gfx90c reference was measured against.
- The Tensile checkout (`rocm-libraries/shared/tensile`).
- `cmake ≥ 3.21`, `amdclang++` (from the SDK).
- Optional: an API key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OTO_API_KEY`)
  for the agent-research phase.

## 2. Easy mode (recommended)

```bash
python3 -m oto setup --yes          # prepare toolchain + .env + client
python3 -m oto setup                # guided walk
python3 -m oto setup --dry-run      # print the plan only
```

`--yes` runs the whole flow non-interactively with the defaults (blind
convergence, the first complete ROCm SDK it finds, the first Tensile checkout
it finds, gfx90c GPU targets, builds the client, writes `.env`).

Both the SDK and the Tensile checkout can also be installed on request —
easy mode never downloads anything you did not ask for:

```bash
python3 -m oto setup --yes --download-rocm python --rocm-venv ~/rocm-venv \
    --download-tensile clone --tensile-dest ~/rocm-libraries   # sparse clone of ROCm/rocm-libraries
```

`--download-rocm python` creates a venv and installs the gfx90c nightly
wheels from `rocm.nightlies.amd.com/whl-multi-arch/` (add `--download-torch`
for torch 2.12.0/torchvision 0.27.0/torchaudio 2.11.0). `--download-rocm dnf`
prints package guidance instead of invoking sudo. Interactively, the wizard
asks; non-interactively without the flags it downloads nothing.

## 3. What it asks (and the good defaults)

| Step | Question | Default | Why |
|---|---|---|---|
| 1 | Convergence mode — blind or informed? | blind | Most new devices have no reference floor |
| 2 | Spoof (reference floor) codename (informed only) | gfx900 | The shipped floor; community-popular spoof |
| 3 | ROCm flavour — python (venv) or opt | python | Must be a *full* SDK (§4) |
| 4 | ROCm version policy — nightly or pinned | nightly | Nightly is what gfx90c was measured against |
| 5 | Pinned ROCm version (if pinned) | 7.15.0a20260728 | Recorded in `.env` |
| 6 | Tensile version policy — nightly or pinned | pinned | gfx902 bookkeeping landed at a specific commit |
| 7 | Pinned Tensile commit/SHA (if pinned) | (current checkout) | Recorded in `.env` |
| 8 | HIP/clang version | (from SDK) | `amdclang++ --version` |
| 9 | ROCm install (auto-detected complete SDKs) | first found | Must be a full SDK (§4) |
| 10 | Tensile checkout (auto-detected) | first found | Must contain `Tensile/bin/Tensile` |
| 11 | GPU targets for the client build | gfx90c | Re-run with `gfx902` on the target machine |
| 12 | Build the Tensile client? | yes | CPU-only, 2–5 min, never touches a GPU |
| 13 | Write `.env`? | yes | Never overwrites without `--force` |
| 14 | Verify (doctor + deck sanity) | automatic | Honest status |

## 4. The full-SDK rule (the thing that bites)

A ROCm install is **usable** only when it ships a complete HIP include tree:
`<prefix>/include/hip/amd_detail/amd_warp_functions.h` must exist. The marker
is what easy mode checks before accepting any prefix. The python-sdk wheel
layout ships a complete tree — but not the `amd_smi` C headers the Tensile
client links with; those live only in the full tarball (`dist-<ver>`). If the
client build fails on amd_smi, point `--rocm-prefix` at a full dist extraction
or pass `--download-rocm python` and use the wheel-built client instead.
Never let the build resolve HIP headers from `/usr` (ROCm 6) — see the
`__AMDGCN_WAVEFRONT_SIZE` failure it caused in the Nov-2026 probes.

## 5. Manual setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env                # fill TENSILE_ROOT and ROCM_PATH
scripts/build_tensile_client.sh --rocm-prefix <ROCM_PREFIX> \
    --tensile-root <TENSILE_ROOT>
python3 -m oto doctor              # should report 0 FAIL
```

## 6. Non-interactive / CI usage

```bash
python3 -m oto setup --yes --convergence-mode blind --rocm-prefix /path/to/sdk \
    --tensile-root /path/to/rocm-libraries --gpu-targets gfx90c --skip-build
```

`OTO_NO_INPUT=1` makes every prompt take its default.

## 7. What "ready" means after setup

`oto doctor` reports 0 FAIL, then:

```bash
python3 -m oto check candidates --quiet
python3 -m oto agent consult docs/<codename>_starter.md
```

Stage A (CPU-only, no key) is complete. Stage B (starter pair + human
verification gate) and Stage D (GPU, TTY) are the next human steps;
see [`docs/operator/starter_pair.md`](../operator/starter_pair.md).

## 8. Bring-up procedure and failure modes

Stage A–D protocol: [`docs/operator/starter_pair.md`](../operator/starter_pair.md).
Verification matrix and failure modes:
[`docs/operator/operator_runbook.md`](../operator/operator_runbook.md) §7–§9.
Blind/uninformed convergence on gfx902:
[`docs/operator/starter_pair.md`](../operator/starter_pair.md).

## 9. CLI command reference

See [`docs/cli.md`](../cli.md). Easiest entry point:

```bash
python3 -m oto help
python3 -m oto setup --yes
```