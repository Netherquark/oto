# Adding a device: the Markdown+JSON starter pair
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


oto is a device-independent port. A new device enters through a
**starter pair**, never through a code edit:

```
docs/<codename>_starter.md     narrative: what the device is, what you want
docs/<codename>_starter.json   facts: the profile oto loads
```

The markdown says who the device is; the JSON says what it is. Keeping the two in one
file would make either the prose or the machine facts unreadable.

**This file is the master checklist for bringing a device up from zero.** Everything
on the "what must work" path is tagged **PROVEN**,
**BLOCKED** (needs the API key / human verification), or **UNPROVEN**
(silicon-dependent — never assumed). The order below is the order to walk.

## 0. The device-independent bring-up order

Any new device exercises the same gate path. The stages below land in the same order
regardless of the target part; their contents differ.

### Stage A — pre-flight (no GPU, no key)

| Step | Command | What it proves |
|---|---|---|
| A1 | `oto check candidates --quiet` | 280-row deck sane on the ambient profile (280/0 illegal today) |
| A2 | `oto agent consult` (on a stub pair) | Agent pipeline writes a gate-checked `potential_configs.md` |
| A3 | `oto agent index` | Docs index (`docs/docs_index.json`) regenerates |
| A4 | `oto doctor` | Honest status of `.env`/`TENSILE_ROOT`/`ROCM_PATH`/registry |
| A5 | `python3 -m pytest -q` | Suite is green; rehearsal suite covers the class-B path |

These steps are CPU-only and **already runnable**. If A1–A5 pass on your stub,
the repo is ready for a new-device campaign; nothing gfx902-specific has been
added to make that possible.

### Stage B — write the pair and load it

- `docs/<codename>_starter.md` — narrative identity + what you want; it
  loads as the device identity today.
- `docs/<codename>_starter.json` — facts. **A zeroed stub refuses to load**
  (`oto/device/loader.py:load_profile_from_starter` fails loudly). This is the
  gate.
- The agent prints a **directed** research prompt (see `oto/agents/context.guided_question`); with an `OTO_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` the agent fills an `UNVERIFIED` section — with none, the section is simply absent. The agent never invents facts.
- The stub also gates anything downstream: **A real-profile** path is not
  exercisable until the human says "this is an honest gfx902".

### Stage C — human verification gate

A human cross-checks **every** value against first-party sources (AMD ISA
manual, the SKU spec sheet, the rocminfo dump). Only after the human check does
the stub populate into a real profile; promotion to `profiles/<codename>.json`
is a manual copy made by the human.

### Stage D — build on the device itself (TTY only)

- The benchmark client must exist on the host first — it is compiled once,
  CPU-only: `scripts/build_tensile_client.sh --rocm-prefix <ROCM_PREFIX>
  --tensile-root <TENSILE_ROOT>` (contract: `docs/toolchain_client.md`;
  `oto doctor` reports `Tensile client OK` when it lands).
- `oto tune` — needs the device's GPU. This step is *never* run in a desktop
  session; it is for a TTY on the target machine.
- `oto report` — produces `<codename>_results/acceptance_report.{json,html}`.
- `oto check library-parity` — the 38/38-style check the reference device has.

**Each step above is expected on a fresh device**; none required code.

**BLOCKED items (true today, 2026-11-15):**
- `profiles/<codename>.json` — no real gfx902 profile on disk; the stub stays unverified
  until the owner's API key + a human verification of every value.
- No gfx902 silicon on this host to run Stage D on. Nothing else is blocked.

**CPU-side pipeline — READY (verified 2026-11-15):**
- `oto/device/tensile_isa.py:ISA_TRIPLES` carries `gfx902: (9, 0, 0x02)` (public LLVM ISA-version fact).
- Tensile-side gfx902 support landed in the rocm-libraries checkout (commit 386e90e) —
  3 entries: `SupportedISA` gains `(9,0,2)`, `architectureMap["gfx902"] = "vega10"`,
  `AsmCaps[(9,0,2)]` (derived byte-identical to gfx90c's entry via the nightly clang).
- `oto check tensile-build --arch gfx902` passes end-to-end: CC (MT=64x32x16, TT=4x2)
  and ZZ (MT=32x32x16, TT=2x2, sols=1, vgpr≤71) both build; LLVM assembles gfx902
  v_fma_f64 and correctly refuses gfx902 MFMA.
- Tensile client builds (`scripts/build_tensile_client.sh`); `oto doctor` reports 21 ok / 0 FAIL.
- The remaining blockers: profile + human verification + gfx902 silicon + the owner's API key.

**UNPROVEN (no claim, ever):** every assumption about gfx902's behavior in
Tensile — legal accepted knob sets, matrix legality, perf. Nothing in the repo
may claim silicon-dependent facts until the human check produces numbers.

## The sync rule

Both halves carry the codename, and they must agree:

```yaml
# <codename>_starter.md
codename: <codename>
```

```json
// <codename>_starter.json
{ "codename": "<codename>", ... }
```

`oto.device.loader.load_profile_from_starter()` enforces this: a mismatch is a hard
error, not a warning. Once the values are verified, the JSON half is promoted to
`profiles/<codename>.json` and oto's `--codename <codename>` path works with zero
code changes.

## Division of labor

| Half | Author | Content |
|------|--------|---------|
| `.md` | you (+ agent research) | codename, target SKU, what the tuning run is for, known quirks, API-key *reference* (env var name, never the key) |
| `.json` | you (+ agent research), then **you verify** | full profile schema (see `profiles/gfx90c.json` for a complete example): ISA tuple, CU count, clocks, LDS, peaks, family shapes, ceilings |

## Getting the facts with agent research

`oto agent generate` runs two doc agents against the pair:

* **agent-1** (`oto/agents/theoretical_limits.py`) — emits
  `<codename>_theoretical_limits.md` (peaks, ceilings, hardware section),
* **agent-2** (`oto/agents/tuning_context.py`) — emits
  `<codename>_tuning_context.md` (knob surface, family shapes).

Research is auto-enabled when an API key is visible in the environment:

| Key in env | Backend | Web research |
|------------|---------|--------------|
| `ANTHROPIC_API_KEY` (or `sk-ant-` prefix) | Anthropic Messages API | server-side `web_search` tool (up to 8 uses) |
| `OPENAI_API_KEY` (or other `sk-` token) | OpenAI chat completions | `gpt-4o-mini-search-preview` (override with `OTO_API_MODEL`) |
| `pplx-` prefix | Perplexity chat completions | `sonar` (override with `OTO_API_MODEL`) |
| `OTO_API_KEY` | whatever it looks like, or `OTO_API_ENDPOINT` if set | follows the same rules |

`OTO_API_ENDPOINT` (explicit) always wins; `OTO_API_MODEL` always overrides
the default model; `OTO_API_TIMEOUT` (default 60 s) and
`OTO_API_MAX_TOKENS` (default 2048) tune the call.

**Everything the agents write under `## Research (UNVERIFIED ...)` is unverified.**
The research path exists to *gather candidate facts*; it does not write the profile.
Numbers reach `profiles/<codename>.json` only after a human checks them against
first-party sources (AMD ISA reference, ROCm release notes, the SKU spec sheet). An
agent-researched profile that ships unverified is a bug, not a feature.

## Stage A–D worked example

For this repo, the worked example is the gfx90c family — see `profiles/gfx90c.json`
and the docs here. New devices follow the same Stage A–D walk.

`docs/gfx902_starter.md` + `docs/gfx902_starter.json` are a stub for a device
oto has neither measured nor validated; they exercise the unverified-refusal path.
See `docs/starter_template.md` for a blank template example.

## Minimal recipe

1. Copy `docs/starter_template.md` and `docs/starter_template.json` to
   `docs/<codename>_starter.{md,json}`.
2. Fill the markdown (what you want from the device, known quirks).
3. Fill the JSON with values you can verify, or leave a stub and research:

   ```
   python3 -m oto agent generate docs/<codename>_starter.md
   ```

4. Transcribe the verified facts from the `## Research (UNVERIFIED ...)`
   sections into the JSON; cross-check every number against a first-party
   source; delete nothing until the JSON loads:

   ```
   python -c "from oto.device.loader import load_profile_from_starter; \
              print(load_profile_from_starter('docs/<codename>_starter.md'))"
   ```

5. `mkdir -p profiles && cp docs/<codename>_starter.json profiles/<codename>.json`
   only after verification. From then on `--codename <codename>` works.
6. Verify end to end on the device itself in a TTY (never inside a
   Wayland desktop session): the tuning run, the report, the library.

## What this deliberately does not do

* It does not invent silicon facts. Empty/unverified fields are marked
  in the JSON by omission; the loader fails loudly on missing keys.
* It does not trust agent output. UNVERIFIED sections are inputs to your
  judgement, nothing else.
* It does not run on a device it cannot see. CPU-only steps (doc generation,
  profile synthesis, gates, tests) are fine anywhere; actual tuning runs belong
  in a TTY on the target machine.

## The bring-up gate, restated

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

---

## gfx902 worked example — blind, uninformed convergence (folded)

## 0. What "blind" and "uninformed" mean here

- **Blind**: no reference floor exists for gfx902. There is no shipped library
  to beat, so acceptance is **functional correctness + gate compliance**, not
  WIN/TIE/LOSS. Performance is reported as measured, never extrapolated.
- **Uninformed**: the agent starts with the public identity facts only (LLVM
  `amdgpu9.02` ↔ gfx902, RAVEN / GCN 5 family). Every silicon fact (CU count,
  clock, peaks, instruction support) is zeroed and refuses to load until a
  human verifies it. The agent never invents facts; research sections carry
  **UNVERIFIED** tags.

## 1. Preconditions (stop at the first failure)

1. You are on the target silicon (Ryzen 5 2200G / Raven Ridge, Vega 8).
   `rocminfo | grep -E 'Name|Chip ID|gfx'` must report gfx902. If it does
   not, stop: `--codename` selects a profile, it does not change the silicon.
2. `claude.md` §2.0 applies unchanged.
3. GPU work happens only in the user's TTY. In a desktop session you do
   CPU-only work and stop.
4. Best-effort ≠ converged. This recipe delivers the library + verification
   record, not the multi-week campaign.

## 2. Stage A — CPU-only pre-flight (anywhere, no key, no GPU)

```bash
python3 -m oto setup --yes          # or `oto setup` for the guided walk
python3 -m oto doctor               # honest status; 0 FAIL required
python3 -m oto check candidates --quiet
python3 -m oto agent consult docs/gfx902_starter.md
python3 -m oto agent index
python3 -m pytest -q
```

Edge cases:
- `oto doctor` reports FAIL on the Tensile client → build it first:
  `scripts/build_tensile_client.sh --rocm-prefix <ROCM> --tensile-root <TENSILE>`.
  The client needs a *full* SDK (see `docs/toolchain_client.md`); a python-sdk
  venv's partial `include/hip` shadows nightly headers with `/usr`'s ROCm 6.
- `setup` finds no complete SDK → install TheRock nightly or pass
  `--rocm-prefix`. Never point at a partial venv.
- `setup` finds no Tensile checkout → clone rocm-libraries and pass
  `--tensile-root`.
- Deck sanity fails → the profile is off (clock/LDS/ISA), not the deck.
  Re-verify Stage C.

## 3. Easy-mode onboarding questions (what to answer)

`oto setup` (guided) asks, in order:

1. **Convergence mode** — `blind` (default) or `informed`. For gfx902 the
   first pass is blind; there is no shipped floor to beat.
2. **Spoof (informed only)** — the reference-floor GPU codename. Default
   `gfx900` (the shipped floor oto was built against). Only asked in informed
   mode.
3. **ROCm type** — `python` (TheRock venv) or `opt` (`/opt/rocm*`). Pick the
   one that is a *full* SDK (marker `include/hip/amd_detail/amd_warp_functions.h`).
4. **ROCm version** — `nightly` (recommended, what gfx90c was measured
   against) or a `pinned` version string (e.g. `7.15.0a20260728`). Nightly
   is the default; pin only when reproducing a prior run.
5. **Tensile version** — the commit SHA of the rocm-libraries checkout that
   carries the gfx902 bookkeeping (`shared/tensile`). Record it; do not
   re-derive.
6. **HIP / clang version** — from the chosen SDK's `amdclang++ --version`.
   The assembler prefers the SDK's `amdclang++`; record the reported version.
7. **GPU targets for the client build** — `gfx90c` on the reference box;
   on the gfx902 box pass `--gpu-targets gfx902` (or both).
8. **Build the client?** — yes (CPU-only, 2–5 min).
9. **Write `.env`?** — yes (never overwrites without `--force`).
10. **Verify** — automatic (`oto doctor` + deck sanity).

Defaults are the ones that worked for gfx90c; a human who knows TTY/Linux
basics but not GPU internals can accept them all.

## 4. Stage B — write the starter pair and (optionally) research

```bash
cp docs/starter_template.md docs/gfx902_starter.md
cp docs/starter_template.json docs/gfx902_starter.json
```

Fill the `.md` first (target narrative + research brief). Leave the `.json`
zeroed until verification. The loader enforces codename sync across the pair
and refuses placeholder/zeroed profiles — that refusal is the intended failure
mode, not a bug.

Optional, needs an API key (never commit one):

```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY / OTO_API_KEY
python3 -m oto agent generate docs/gfx902_starter.md
```

Without a key, research is a clean no-op and the docs carry the starter text
only. Non-200 collapses to empty with a status-only stderr note — check the
endpoint/key, do not paste it into files. The key is used in headers only,
never persisted into docs.

CPU-only harness work that degrades gracefully on a fresh device:

```bash
python3 -m oto.harness.corpus_census --family SS --knob DepthU
python3 -m oto.tools.deck_review score
python3 -m oto.harness.candidate_generator --dry-run
```

## 5. Stage C — human verification gate (mandatory, you do not skip)

1. Check every value against first-party sources: AMD ISA reference, ROCm
   release notes / support matrix, SKU spec sheet.
2. Fill `docs/gfx902_starter.json` with verified values, delete its
   `_comment`, set `**UNVERIFIED**`-tagged items to verified replacements (or
   keep the tag if still open).
3. Promote: copy `docs/gfx902_starter.json` → `profiles/gfx902.json`.
4. Sanity-load:
   ```bash
   python3 -c "from oto.device.loader import load_profile; print(load_profile('gfx902'))"
   ```
   A successful load is necessary, not sufficient — the human check is the gate.
5. If `rocminfo` disagrees with the profile, fix the profile, not the code.

**Never** promote a profile without this gate. **Never** present agent research
as measured fact. **Never** strip UNVERIFIED tags to make a doc read better.

## 6. Stage D — build on the device (TTY only)

Build the Tensile client once (CPU-only):

```bash
scripts/build_tensile_client.sh --rocm-prefix <ROCM_PREFIX> \
    --tensile-root <TENSILE_ROOT> --targets gfx902
```

Then, in the user's TTY:

```bash
python3 -m oto tune                 # the device's GPU
python3 -m oto report               # gfx902_results/acceptance_report.{json,html}
python3 -m oto check library-parity
python3 -m oto library best-effort --codename gfx902
```

Interactive controls during every phase (including cooldown sleep):

| Key | Action |
|---|---|
| `s` | Skip current kernel or cooldown sleep |
| `e` | End after iteration, generate reports |
| `q` | Quit & report (kills child process groups, saves state) |
| `Ctrl+C` | Interrupt (130), saves run state |

## 7. Edge cases, failure modes, retries, recovery

Generic failure modes and the honest response are in
[`docs/operator_runbook.md`](operator_runbook.md) §8; the table below lists
gfx902-specific additions.

| Symptom | Cause | Response |
|---|---|---|
| `load_profile` says unverified/placeholder | Starter pair not filled/promoted | Fill + verify (Stage C). Do not patch the gate. |
| Agent returns empty research | No key, or non-200 | Set a key or run without; docs carry starter text only. Check endpoint/key; never paste keys into files. |
| Auto-detect picks the wrong device | Multiple installs | Pass `--codename gfx902` and `--rocm-prefix` explicitly. Never edit peaks to match silence. |
| Corpus missing on first run | Expected on a new device | `harness-study` reports "no kernel_db.json". Start with `oto library best-effort` for the floor-less build. |
| Gates reject every proposal | Profile is off (clock/LDS/ISA) | Re-verify Stage C. The generator is profile-driven; a rejection storm is a profile bug, not a deck bug. |
| ROCm reports the arch as unsupported | Toolchain/ISA gap | Stop. Record the blocker in `docs/incomplete_work.md`. Do not widen `gates/`. |
| `__AMDGCN_WAVEFRONT_SIZE` errors | Partial-SDK header shadowing | Use the full extracted dist, not a python-sdk venv. |
| `amd_smi` cmake config missing | ROCm 6.4.x prefix | Use a 7.x SDK. |
| Kernel ring timeout / DE crash | Memory/register pressure on the APU | Record the case; reduce occupancy; do not widen gates. Thermal cooldown between runs. |
| Thermal instability | Mobile APU frequency/power | Use the repeat-and-cooldown policy; do not skip cooldowns. |
| Abandoned run in registry | Append-only ledger | Leave it; `oto check db` keeps reporting it. Do not edit the ledger. |
| Want to relax 60-line/600-line/pyflakes/ruff/py_compile/ledger rules | Temptation | No. See `claude.md` §2.0 and `docs/harness_runbook.md`. |

## 8. Dead ends (documented, do not re-raise without new info)

- Spoofing gfx900 on gfx902 hardware gives a baseline but not a native
  library; it is a diagnostic, not a deliverable.
- Mixed-version stacks (ROCm 6 system + nightly headers) silently resolve
  wrong headers; the full-SDK rule exists to prevent this.
- Containerised vendor stacks isolate a failure layer but do not produce a
  native library; use them only for diagnosis.
- Source builds of the whole ROCm stack are the last resort, not the first
  step.
- `AssertFree0/1ElementMultiple=4` (AF4/4) paired-widen is TTY-gated and
  unscheduled; no performance claim exists until it is measured.

## 9. Retry and resume

- The convergence ledger is append-only. Conflicts/verdicts follow the
  acceptance framework; on a new platform acceptance is functional
  correctness + gate compliance.
- Re-run `oto tune` to resume; already-passed decks are still interruptible.
- Rebuild the kernel DB before quoting numbers:
  `python3 -m oto.harness.kernel_db --rebuild`.
- A successful `load_profile` is necessary, not sufficient; re-run the human
  gate if silicon facts change.
- Never delete or truncate `docs/incomplete_work.md`, `docs/gfx902_results.md`, or
  the ledger.

## 10. Verification matrix — what "done" means (best-effort)

| Gate | How | Done when |
|---|---|---|
| Profile refuses placeholders | loader sanity check | Stage C passes |
| Docs carry provenance + UNVERIFIED tags | read the four `gfx902_*.md` | every silicon fact cited or tagged |
| Library builds **(TTY)** | `oto library best-effort` | `TensileCreateLibrary` exits 0; emits `TensileLibrary.dat` |
| Anti-alias scan | built-in post-build check | no foreign-arch tokens |
| Kernels compile **(TTY)** | build log | 0 failed kernels (or triaged + recorded) |
| Functional check **(TTY)** | PyTorch loads library; GEMM vs reference | outputs match within dtype tolerance |
| Verification record | `docs/incomplete_work.md` + `docs/gfx902_results.md` updated | gaps recorded, none hidden |

Functional match is the acceptance bar that exists on every platform.
Performance claims are reported as measured, never extrapolated.

## 11. What you must never do

- Promote a profile `.json` without the human verification gate (Stage C).
- Present agent research as measured fact, or strip UNVERIFIED tags.
- Invent CU counts, clocks, peaks, or instruction support.
- Run benchmarks or builds outside the user's TTY.
- Delete or truncate `docs/incomplete_work.md`, `docs/gfx902_results.md`, or the
  append-only ledger.
- Commit `command.txt`, API keys, or session context files.

## 12. Reading order (class B, gfx902)

`claude.md` (§2.0 only) → `docs/operator_runbook.md` →
`docs/operator_runbook.md` → `docs/starter_pair.md` →
`docs/harness_runbook.md` → this file → `docs/gfx902_starter.md` → the module
docstring of anything you edit.

## 13. Token efficiency (optional)

Long run reports can be compressed with the caveman skill
(`docs/skills/caveman.md`; upstream `vendor/caveman/skills/caveman/SKILL.md`).
Verdicts, numbers, run ids, error strings, commands, evidence tags, and the
data-preservation law stay verbatim under every intensity level; only
narration compresses. Switch with `/caveman lite|full|ultra`; auto-clarity
drops it for security warnings, irreversible confirmations, and ambiguous
multi-step sequences. Default is normal.
