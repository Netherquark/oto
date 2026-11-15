# Getting started with oto

The full guide to bringing oto up on a box, running a campaign, and
producing a best-effort library. For the birds-eye view of the project
documentation, see [`docs/overview.md`](overview.md). For the philosophy,
see [`README.md`](../README.md).

## 1. Prerequisites

- Linux (Fedora 43 / RHEL 9.x tested), Python ≥ 3.10.
- An AMD GPU oto has never seen (gfx90c, gfx902, …).
- A ROCm 7.x install (TheRock nightly recommended) — Python SDK venv
  or extracted tarball. **Never** the ROCm 6.4.x system install for new
  work; the nightly is what the gfx90c reference was measured against.
- The Tensile checkout (`rocm-libraries/shared/tensile`).
- `cmake ≥ 3.21`, `amdclang++` (from the SDK).
- Optional: an API key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
  `OTO_API_KEY`) for the agent-research phase.

## 2. Easy mode (recommended)

```bash
git clone <this repo> && cd oto
python3 -m oto setup --yes
```

That runs the whole flow non-interactively with the defaults (blind
convergence, the first complete ROCm SDK it finds, the first Tensile
checkout it finds, gfx90c GPU targets, builds the client, writes `.env`,
runs `oto doctor` and the deck sanity check). If anything is missing it
prints the exact command to fix it and stops.

For a guided walk:

```bash
python3 -m oto setup              # asks each question, accepts defaults
python3 -m oto setup --dry-run    # prints the plan and the .env it would write
```

See [`docs/setup.md`](setup.md) for the full question flow, the full-SDK
rule, and troubleshooting.

## 3. Manual setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt    # pinned, known-good set
pip install -r requirements-dev.txt  # dev suite; needs this
cp .env.example .env               # fill TENSILE_ROOT and ROCM_PATH
```

Then build the Tensile client (CPU-only, never touches a GPU):

```bash
scripts/build_tensile_client.sh --rocm-prefix <ROCM_PREFIX> \
    --tensile-root <TENSILE_ROOT>
python3 -m oto doctor              # should report 0 FAIL
```

The client needs a *full* SDK prefix (`<prefix>/include/hip/amd_detail/
amd_warp_functions.h` must exist). A python-sdk venv ships a partial
`include/hip` and will shadow the nightly headers with `/usr`'s ROCm 6
headers — use the full extracted dist. See
[`docs/toolchain_client.md`](toolchain_client.md).

## 4. Interactive runtime controls

During execution the interactive single-key listener is active on `stdin`
in **every** phase of a run — while a benchmark kernel is running, during
thermal cooldown sleep, and while phases are being skipped. Skipping is not
a gap in the key handling; a re-run of an already-passed deck is still
interruptible.

| Key | Action | Description |
|---|---|---|
| `s` | Skip | Skips the current running benchmark kernel or the remaining thermal cooldown sleep. |
| `e` | End after iteration | Lets the current phase finish, then gracefully ends the run and generates `acceptance_report.json` + `.html`. |
| `q` | Quit & Report | Gracefully terminates, kills active child process groups, generates reports from data collected so far. |
| `Ctrl+C` | Interrupt (130) | Kills all child process groups and exits with status 130 after saving run state. |

## 5. Bring a new device up from zero

Every new device exercises the same gate path. The order is the order in
which to walk it; the contents differ per part.

### Stage A — pre-flight (no GPU, no key)

| Step | Command | What it proves |
|---|---|---|
| A1 | `oto check candidates --quiet` | Deck sane on the ambient profile |
| A2 | `oto agent consult` (on a stub pair) | Agent pipeline writes a gate-checked `potential_configs.md` |
| A3 | `oto agent index` | Docs index regenerates |
| A4 | `oto doctor` | Honest status of `.env` / `TENSILE_ROOT` / `ROCM_PATH` / registry |
| A5 | `python3 -m pytest -q` | Suite green; rehearsal suite covers the class-B path |

### Stage B — write the starter pair and load it

- `docs/<codename>_starter.md` — narrative identity + what you want.
- `docs/<codename>_starter.json` — facts. A zeroed stub refuses to load
  (`oto/device/loader.py:load_profile_from_starter` fails loudly). This is
  the gate, not a bug.
- With an API key, `oto agent generate` / `oto agent consult` fills an
  `UNVERIFIED` section; with none, the section is simply absent. The agent
  never invents facts.

### Stage C — human verification gate (mandatory)

Cross-check every value against first-party sources (AMD ISA reference, ROCm
release notes, SKU spec sheet). Promote `docs/<codename>_starter.json` →
`profiles/<codename>.json` only after verification. A successful
`load_profile` is necessary, not sufficient.

### Stage D — build on the device itself (TTY only)

- Build the Tensile client first (CPU-only, once):
  `scripts/build_tensile_client.sh --rocm-prefix <ROCM_PREFIX> \
  --tensile-root <TENSILE_ROOT>` (see `docs/toolchain_client.md`).
- `oto tune` — the device's GPU. Never in a desktop session.
- `oto report` — produces `<codename>_results/acceptance_report.{json,html}`.
- `oto check library-parity` — the shipped-cell coverage check.

### The bring-up gate, restated

```
   A1  Deck sanity                         — anywhere, no key
   A2  Agent consult                       — anywhere, no key
   A3  Agent index                         — anywhere
   A4  Doctor reports honestly             — reports what is present
   A5  pytest green                        — gates every edit
  ─────  human verification gate  ─────
   C   VERIFIED profile promoted           — a human decision
  ─────  device runs in a TTY only ─────
   D   tune / report / parity              — TTY-driven, GPU-required
                                             (client built once, CPU-only:
                                              scripts/build_tensile_client.sh;
                                              see docs/toolchain_client.md)
```

A new device is ready when Stage A passes on its stub and the silicon is
verified to behave. Everything between is a human's call.

## 6. The verification matrix — what "done" means for best-effort

Best-effort is the floor, not the goal. Once the library builds and the
verification matrix passes, the campaign — the multi-session work that
turns a working library into a converged one — is specified in
[`docs/operator_campaign.md`](operator_campaign.md).

| Gate | How | Done when |
|---|---|---|
| Profile refuses placeholders | loader sanity check | §4 sanity load passes |
| Docs carry provenance + UNVERIFIED tags | read the four `<codename>_*.md` | every silicon fact cited or tagged |
| Library builds **(TTY)** | `oto library best-effort` | `TensileCreateLibrary` exits 0; outputs `TensileLibrary.dat` |
| Anti-alias scan | oto's built-in post-build check | no foreign-arch tokens found |
| Kernels compile **(TTY)** | build log | 0 failed kernels (or failures triaged and recorded) |
| Functional check **(TTY)** | PyTorch loads the library; GEMM vs reference on random inputs | outputs match reference within dtype tolerance |
| Verification record | `incomplete_work.md` + `docs/<codename>_results.md` updated | gaps recorded, none hidden |

## 7. Failure modes and the honest response

| Symptom | Response |
|---|---|
| `load_profile` says unverified/placeholder | Fill + verify the starter pair (Stage C). Do not patch the gate. |
| Agent returns empty research | Set a key (§3) or run with none; the docs then carry the starter text only. Non-200 collapses to empty with a status-only stderr note — check your endpoint/key, do not paste it into files. |
| Auto-detect picks the wrong device | Pass `--codename <codename>` explicitly; never edit peaks to match silence. |
| Corpus missing on first run | Expected; `harness-study` reports "no kernel_db.json". Start with `oto library best-effort` for the floor-less build. |
| Gates reject every proposal | The generator is profile-driven; a rejection storm means the profile is off (clock/LDS/ISA), not that the deck is wrong. Re-verify §4. |
| ROCm reports the arch as unsupported | Stop. Record the blocker in `incomplete_work.md`. Do not widen `gates/` to force it through. |
| You want to relax the 60-line / 600-line / pyflakes / ruff / py_compile / ledger rules to move faster | No. See `claude.md` §2.0 and `docs/harness_runbook.md` guardrails. |

## 8. What you must never do

- Promote a profile `.json` without the human verification gate (Stage C).
- Present agent research as measured fact, or strip UNVERIFIED tags to make
  a doc read better.
- Invent CU counts, clocks, peaks, or instruction support for any GPU.
- Run benchmarks or builds outside the user's TTY.
- Delete or truncate `incomplete_work.md`, `docs/<codename>_results.md`, or the
  append-only ledger.
- Commit `command.txt`, API keys, or session context files.

## 9. Reading order (class B)

`claude.md` (shared invariants only) → [`docs/operator_runbook.md`](operator_runbook.md) →
[`docs/operator_campaign.md`](operator_campaign.md) (the tuning campaign; §18 is the
research-prompt discipline for commissioning research passes) →
[`docs/README.md`](README.md) (the registry) →
[`docs/starter_pair.md`](starter_pair.md) → [`docs/agent_reference.md`](agent_reference.md) →
`docs/README.md` (the file-ownership and contract boundary) → the module
docstring of anything you edit.

## 10. CLI command reference

See [`docs/cli.md`](cli.md) for the full command vocabulary, flags, and the
migration table from the old root-shim names. For the easiest entry point:

```bash
python3 -m oto help
python3 -m oto setup --yes
```
