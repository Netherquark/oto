# oto operator runbook — a best-effort Tensile library on an unsupported AMD platform

**Class B document.** Read this if you are an agent operating oto against a
GPU oto has never seen, or a human supervising that agent. If you are a
coding agent working **on** oto, you are in the wrong file — read
`claude.md` and [`docs/README.md`](README.md) first.

This runbook is the contract for the *best-effort* deliverable: a native
Tensile library for a target AMD GPU that AMD does not ship one for, produced
with oto, verified as far as honestly possible **without** inventing hardware
facts and **without** running the GPU in a display session. It is not a
recipe for the full convergence campaign (that is `implementation_plan.md`'s
job on the reference target), and it never overrides `claude.md`.

## 0. Hard preconditions — stop at the first failure

1. **You have a target codename** (e.g. from `rocminfo`), not a vendor string.
2. **Hardware matches the codename.** `rocminfo | grep -E 'Name|Chip ID'`.
   If the box you are on is a different GPU, stop: `--codename` selects a
   profile, it does not change the silicon.
3. **`claude.md` §2.0 applies to you unchanged**: no re-deriving settled
   facts, append-only ledger, one owner per fact. Where this runbook and
   `claude.md` disagree, `claude.md` wins.
4. **GPU work happens only in the user's TTY.** In a Wayland/desktop session
   you do CPU-only work and stop. Every GPU step below is marked **(TTY)**.
5. **Best-effort ≠ converged.** A best-effort library builds, compiles its
   kernels, passes oto's structural gates, and loads/dispatches through
   PyTorch. Convergence to parity is a multi-week benchmark campaign on the
   user's TTY; this runbook delivers the library + verification record, not
   the campaign.

## 1. Identify the device, honestly (read-only)

```bash
rocminfo | grep -E 'Name|Chip ID|gfx|Max Clock|Compute Unit'
```

Record exactly what you see. Everything below this line is either verified
by you against first-party sources or marked UNVERIFIED — never guessed.
Do not infer peaks from clock × CUs by "standard" formulas without showing
the arithmetic in the starter file.

## 2. The starter pair (mandatory for a new platform)

Read [`docs/starter_pair.md`](starter_pair.md) — the protocol. In short:

- `docs/<codename>_starter.md` — narrative half: target, why, open questions.
- `docs/<codename>_starter.json` — machine half: every profile field.
- The loader enforces **codename sync** across the pair and refuses
  placeholder/zeroed profiles. A stub you have not filled is a stub you
  cannot tune against — that is the intended failure mode, not a bug.
- [`docs/gfx902_starter.md`](gfx902_starter.md) + [`docs/gfx902_starter.json`](gfx902_starter.json)
  are the worked example: public identity facts only (LLVM
  `amdgpu9.02` ↔ gfx902; public tables list RAVEN / GCN 5 family), every
  silicon fact zeroed, load-refusal covered by a test.

To start:

```bash
cp docs/starter_template.md docs/<codename>_starter.md
cp docs/starter_template.json docs/<codename>_starter.json
```

Fill the `.md` first (target narrative + research brief). Leave the `.json`
zeroed until verification (§4).

## 3. Let the agents research (optional, needs an API key)

Set one key in the shell that runs the command (never commit one):

```bash
export ANTHROPIC_API_KEY=...   # sk-ant- → Messages API + server-side web_search
export OPENAI_API_KEY=...      # sk-*   → gpt-4o-mini-search-preview
export OTO_API_KEY=pplx-...    # pplx-  → Perplexity sonar
export OTO_API_ENDPOINT=...    # explicit endpoint always wins (OTO_API_MODEL too)
```

```bash
PYTHONPATH=. python3 port_tensile.py --generate-device-docs docs/<codename>_starter.md --codename <codename>
```

The agent writes `docs/<codename>_theoretical_limits.md` and
`docs/<codename>_tuning_context.md` with research sections marked
**UNVERIFIED**, plus `docs/<codename>_harness_study.md` and
`docs/<codename>_potential_configs.md` (both CPU-only; see §6). Without a
key, research is a clean no-op and the docs carry the starter text only.
If the target already has `profiles/<codename>.json`, you may omit the
starter path: `--generate-device-docs --codename <codename>`.

**Agent research is advisory. It is never the source of record for silicon
facts.** See §4.

## 4. The human verification gate (mandatory — you do not skip this)

The agent's numbers may be wrong in ways tests cannot catch. Before any
`.json` is filled:

1. Check every value against first-party sources: AMD ISA reference,
   ROCm release notes / support matrix, and the SKU spec sheet.
2. Fill `docs/<codename>_starter.json` with verified values, delete its
   `_comment`, and set `**UNVERIFIED**`-tagged items to their verified
   replacements in `docs/<codename>_starter.md` (or keep the tag if a
   fact is still open).
3. Promote it: copy `docs/<codename>_starter.json` → `profiles/<codename>.json`.
4. Sanity-load it:

   ```bash
   PYTHONPATH=. python3 -c "from oto.device.loader import load_profile; print(load_profile('<codename>'))"
   ```

   The loader refuses placeholders and zeroed silicon. A successful load is
   necessary but not sufficient — the human check in step 1 is the gate.
5. If the target's `rocminfo` disagrees with the profile, stop and fix the
   profile, not the code.

## 5. (TTY) Benchmark campaign — user-driven

Best-effort still starts with measurement. In the user's TTY:

1. Run oto's driver stages for the target (`port_tensile.py` stage list and
   the interactive controls are documented in `README.md` §3).
2. The kernel corpus accumulates in `gfx90c_results/analysis/kernel_db.json`
   — the path is historical, not device; on the target device the corpus is
   whatever the runs on that device produced. 30 minutes to boot the corpus;
   days to converge.
3. The convergence ledger is append-only; conflicts/verdicts follow the
   acceptance framework in `gfx90c_theoretical_limits.md` — **for the
   reference target only**. On a new platform, like-for-like against a
   shipped floor may not exist (there may be no reference library to beat):
   then acceptance is functional correctness + gate compliance, and you
   record that honestly instead of inventing a floor.

## 6. CPU-only harness work (any session, including now)

These work before any GPU run exists, on any device:

```bash
python3 -m oto.harness.corpus_census --family SS --knob DepthU   # corpus history
python3 -m oto.tools.deck_review score                            # deck sanity
python3 -m oto.harness.generate_candidates --dry-run               # candidate pool size
```

`--generate-device-docs` additionally synthesises:

- `docs/<codename>_harness_study.md` — corpus census (runs, floor vs native
  rows), TARGET_CELLS coverage, native winners per cell, and 16 round-robin
  proposals annotated by the CPU gates. **CPU-checked ≠ benchmarked.**
- `docs/<codename>_potential_configs.md` — ceilings + corpus + acceptance
  summary synthesised from the same inputs.

On a fresh device these degrade gracefully ("no kernel_db.json") and the
proposals still generate and gate-check. Analysis guides for each tool:
[`docs/harness_runbook.md`](harness_runbook.md); CPU-only command card:
[`docs/agent_reference.md`](agent_reference.md).

## 7. Verification matrix — what "done" means for best-effort

| Gate | How | Done when |
|---|---|---|
| Profile refuses placeholders | loader sanity check | §4 sanity load passes |
| Docs carry provenance + UNVERIFIED tags | read the four `<codename>_*.md` | every silicon fact cited or tagged |
| Library builds **(TTY)** | `--best-library --codename <codename>` | `TensileCreateLibrary` exits 0; outputs `TensileLibrary.dat` |
| Anti-alias scan | oto's built-in post-build check | no foreign-arch tokens found |
| Kernels compile **(TTY)** | build log | 0 failed kernels (or failures triaged and recorded) |
| Functional check **(TTY)** | PyTorch loads the library; GEMM vs reference on random inputs | outputs match reference within dtype tolerance |
| Verification record | `incomplete_work.md` + `results.md` updated | gaps recorded, none hidden |

Functional match is the acceptance bar that exists on every platform.
Performance claims are reported as measured, never extrapolated.

## 8. Failure modes and the honest response

| Symptom | Response |
|---|---|
| `load_profile` says unverified/placeholder | Fill + verify the starter pair (§4). Do not patch the gate. |
| Agent returns empty research | Set a key (§3) or run with none; the docs then carry the starter text only. Non-200 collapses to empty with a status-only stderr note — check your endpoint/key, do not paste it into files. |
| Auto-detect picks the wrong device | Pass `--codename <codename>` explicitly; never edit peaks to match silence. |
| Corpus missing on first run | Expected; `harness-study` reports "no kernel_db.json". Start with `--best-library` for the floor-less build. |
| Gates reject every proposal | The generator is profile-driven; a rejection storm means the profile is off (clock/LDS/ISA), not that the deck is wrong. Re-verify §4. |
| ROCm reports the arch as unsupported | Stop. Record the blocker in `incomplete_work.md`. Do not widen `gates/` to force it through. |
| You want to relax the 60-line / 600-line / pyflakes / ruff / py_compile / ledger rules to move faster | No. See `claude.md` §2.0 and `docs/harness_runbook.md` guardrails. |

## 9. What you must never do

- Promote a profile `.json` without the human verification gate (§4).
- Present agent research as measured fact, or strip UNVERIFIED tags to make
  a doc read better.
- Invent CU counts, clocks, peaks, or instruction support for any GPU.
- Run benchmarks or builds outside the user's TTY.
- Delete or truncate `incomplete_work.md`, `results.md`, or the append-only
  ledger.
- Commit `command.txt`, API keys, or session context files.

## 10. Reading order (class B)

`claude.md` (shared invariants only) → this file → [`docs/README.md`](README.md) (the registry) →
[`docs/starter_pair.md`](starter_pair.md) → [`docs/agent_reference.md`](agent_reference.md) →
[`plans/REFACTOR_2_UNIVERSAL_GPU.md`](../plans/REFACTOR_2_UNIVERSAL_GPU.md) → the module
docstring of anything you edit.
