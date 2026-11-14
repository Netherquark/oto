# MASTER PLAN — oto universal, autonomous, open-source ready

**Status:** LIVE — updated 2026-11-14. This is the single document a new
agent (or a resumed session after compaction) reads to know where the project
is, what is owed, and in what order to do it. It is not a history essay; it is
a contract. Every item here is either `DONE`, `OPEN`, `BLOCKED`, or
`OWNER-ONLY`.

**Companion slice plans** (in `plans/`):
- `REFACTOR_2_UNIVERSAL_GPU.md` — the device-independence refactor (executed).
- `CLI_UX_REWORK.md` — the `oto` front door (implemented).
- `AGENTIC_POTENTIAL_CONFIGS_PLAN.md` — automated consult → `potential_configs.md`.
- `RENAME_AND_DOC_CLEANUP_PLAN.md` — rename + doc cleanup proposal.
- `test_optimization.md` — suite speed-up roadmap.

**Canonical entry contract**: `claude.md` (§2.0 invariants, §5 guardrails, §9
task routing). This plan never overrides it; where they disagree, `claude.md`
wins.

---

## 0. Mission in one paragraph

oto is a Tensile-tuning harness for AMD GPUs that upstream AMD does not ship a
library for. The user drops in a codename + a starter file (+ an API key), and
oto auto-detects the hardware, derives the device's theoretical limits,
generates the four device docs, builds a best-effort `TensileLibrary.dat`,
and runs the convergence loop — unattended, in the user's TTY, with the GPU
never touched from a display session. gfx90c (Ryzen 5 PRO 5650U, Vega 7) is
the first target and the validation target; gfx902 (Ryzen 5 2200G) is the
second. Everything device-specific is data; the code is device-independent.

## 1. The two development models the operator supports

| model | when it applies | the agent's job |
|---|---|---|
| **Informed convergence** | a spoof reference library exists for a related arch (gfx90c → gfx900) | measure native vs floor; steal floor geometry for worst cells with documented tweaks; retire losers |
| **Blind convergence** | no floor exists; first port of the silicon | derive roofs from the profile mathematically (§7); propose the full 38-cell matrix from GCN geometry intuitions + small tests; measure; converge |

The operator agent does not know which model applies until it reads
`spoof_reference` in the profile. Both models share §7–§9.

## 2. The two agent classes (from `docs/README.md`)

- **Class A — developer** (works **on** oto): entry `claude.md` →
  `docs/agent_reference.md`. May edit code, tests, docs. Owns the gates,
  profile schema, the deck, the harness.
- **Class B — operator** (uses oto to produce a library for an unsupported
  platform): entry `docs/operator_runbook.md` → `docs/operator_campaign.md`.
  **Read-only on the oto codebase.** Writes only its campaign artifacts
  (`<codename>_results/`, `<codename>_runs/`, starter pair, generated device
  docs). Never edits `oto/`, `tests/`, `docs/`, `profiles/`, `phases.yaml`,
  `registry.db`, `.env`. Reports defects in `<codename>_results/bugs.md`.

## 3. Phase history (DONE)

| phase | commit(s) | what |
|---|---|---|
| Attempt 1 (shell) | 2026-07 → 2026-09 | 8.7K-LoC shell suite; ruler math broken 4 ways; retired |
| Attempt 2 (draft) | 2026-09-20 | parallel draft branch; triage → append-only import; acceptance gate rejected |
| oto birth | 2026-09-17 | Python port; corpus + ledger + mutator + report |
| Refactor 1 | 2026-10-10…15 | flat root → `oto/` package; ≤60 LoC/fn, ≤600 LoC/file; 9× faster suite |
| Refactor 2 | 2026-11-13…14 | DeviceProfile, auto-detect, two-agent docs, universal runner, C2.5–C2.9 threading |
| CC:256 AF4/4 Option B | 9645206 | deck rows first-class (279→280; CC 47→48) |
| Deterministic limits | c903b01 | `oto/device/derive.py` + tests |
| Toolchain contract | 5f2b9bb | ROCM_PATH mandatory, no system fallback |
| Hardware-adaptive suite | 895d9c0, ced104d | probe_test rename, corpus skip guards, /tmp scrub |
| Operator playbook | 16c1524, 0f2e4da, 8b10053, 9805f79, 41724a1 | self-contained campaign doc |
| Rename plan | 6703c8d, 93ddaef | proposal only |

## 4. Open work register (current)

### 4.1 Blocked on owner / keys

| ID | item | blocker | owner action |
|---|---|---|---|
| C4 | gfx902 starter research (agent-1/agent-2) | API key | provide key |
| C7.1 | `profiles/gfx902.json` | C4 + human review | approve numbers |
| CC-perf | TTY A/B of CC:256/512 AF4/4 vs AF2/2 | TTY session | run benchmark |
| HIP_PATH | canonical choice (venv vs dist SDK) | owner decision | confirm |
| tarball | 9.9 GB deletion | owner's word | "delete" |

### 4.2 Not started (owner-internal)

| ID | item | what's in tree | next step |
|---|---|---|---|
| CAVEMAN | gfx90c tuning guide → caveman-full | guide is professional prose | rewrite §0-§12 |
| RENAME | rename plan implementation | `plans/RENAME_AND_DOC_CLEANUP_PLAN.md` proposal | owner answers §11 questions, then Phase A |
| AGENTIC | agentic consult implementation | design doc only | implement per plan §1-§9 |
| DOCS-SCAN | docs ecosystem scrub | shell audit only | retry subagents; scrub /tmp + run-id refs |
| GFX902-VAL | gfx902 validation run | needs profile + hardware | after C4 + C7.1 |

### 4.3 What the operator agent cannot do alone

- Edit `oto/`, `tests/`, `profiles/`, `phases.yaml`, `docs/`, `.env`, `registry.db`.
- Run GPU work outside a TTY.
- Spawn research without permission + key.
- Claim convergence from CPU gates.
- Run `git push`.

## 5. The two agent classes — concrete file map

| class | entry | reads | writes |
|---|---|---|---|
| A — developer | `claude.md` | `docs/agent_reference.md`, `docs/docstrings.md`, `docs/harness_runbook.md`, `implementation_plan.md` | `oto/**`, `tests/**`, `docs/**`, `plans/**`, `changelog.md`, `incomplete_work.md`, `results.md`, `potential_configs.md` |
| B — operator | `docs/operator_runbook.md` → `docs/operator_campaign.md` | starter pair, generated device docs, `docs/agent_reference.md`, `docs/comparability.md` | `profiles/<cn>.json`, `docs/<cn>_starter.{md,json}`, generated device docs, run artifacts under `<cn>_results/` and `<cn>_runs/` |

## 6. The convergence pipeline (operator, fully automatic once started)

```
starter file → oto doctor → oto agent generate → oto library best-effort
→ oto check candidates → oto tune --budget 10 --mutations 3
→ oto report --json → (next batch) → ...
```

- `oto doctor`: environment + ROCm + profile + registry + docs.
- `oto agent generate <starter>`: agent-1 (limits doc, derived), agent-2
  (tuning context), harness study (CPU-only), potential_configs synthesis.
- `oto library best-effort`: carve a `TensileLibrary.dat` from the corpus
  winners (38 cells); carve-only, no GPU dispatch.
- `oto check candidates`: gate-legal sweep of `phases.yaml`.
- `oto tune`: the convergence loop (harvest → mutate ≤2 knobs → gate → TTY
  benchmark → verdict → ledger update; novelty enforced by fingerprint).
- `oto report --json`: acceptance report (per-cell verdicts, red/orange lists,
  clock coverage, like-for-like basis).

## 7. Theoretical limits — derived, not transcribed

`oto/device/derive.py`:
- `lanes = num_cus * simds_per_cu * lanes_per_simd`
- FP32 = 2 · lanes · fGHz (f = max_clock_mhz / 1000)
- FP16 = 2 × FP32 (fast F16); BF16 = FP32 (no packed bf16 on GCN5)
- FP64 = FP32 / 16 (GCN5 rate)
- INT8 = FP32 (no dot / dp4a)
- Complex families inherit their lane class (CC → FP32; ZZ → FP64)
- `bandwidth_gb_s = memory_channels * memory_rate_mtps * 8 / 1000`
- `machine_balance = peak / bandwidth` (FLOP/byte)

`tests/test_derive.py` locks it (15 tests). agent-1's `_peak_table` emits the
derivation; the limits doc can never drift from the formula.

## 8. Candidate generation — five strategies

| strategy | mechanism | where it won | when to use |
|---|---|---|---|
| NARROW | 1–3 knob deltas on the parent winner, gated + novelty-checked | DD:192/256/512 @32x32: +267/+20/+7 % | default lever (cheapest) |
| WIDE | tile donors (measured winners or floor winner) × forward-knob draws | HPA 512-band still 91 % unexplored | after NARROW saturates a cell |
| DIRECTION | one knob at a time toward the floor winner | CC:256 (the only steal that worked) | informed mode; fastest path to match floor |
| EXPLORE | virgin axes never co-varied with the winner tile | CC:256 LdsPadB ∈ {1,2,4}; StaggerU=0 (free probe) | where the census marks an untried axis |
| STEAL | floor-winner config as the starting point, documented retune | CC:256 (`AssertFree0/1ElementMultiple: 4`) | informed mode only, worst cells first |

Hierarchy: NARROW > WIDE > DIRECTION; EXPLORE on census-marked virgin axes;
STEAL informed-only. Reading order before proposing:
`corpus_census --cell FAM:side` → `resolve_cells --taxonomy` → `oto check candidates`.

## 9. The bounded problem (the lessons)

Nine rules the corpus earned (full text in `docs/operator_campaign.md` §11A):

1. **L1** — Benchmarks vary inside the noise; anchor verdicts outside it.
2. **L2** — Like-for-like is the only truth; protocol is not visible from names.
3. **L3** — Vendor benchmarks under-report complex work (×4).
4. **L4** — The launcher's refusal IS the silicon.
5. **L5** — Measurement order is not neutral.
6. **L6** — Structural locality travels; byte-copying does not.
7. **L7** — Stealing is informed-mode only and always a retune.
8. **L8** — An axis that never reaches the writer is a placebo.
9. **L9** — Gates are not suggestions — they encode silicon facts.

## 10. Guardrails (never violated)

- No GPU work outside the user's TTY.
- CPU gates are not measurement; only TTY benchmarks decide.
- Typecode is attribution; no phase-stamp trust.
- Clock coverage or nothing; weak `*_clock_coverage` → NULL verdicts.
- Append-only law for registry.db, kernel_db.json, reports.
- Like-for-like: verdicts compare under one protocol.
- Absolute values across runs with different SCLK are not comparable.
- Walls are walls; do not re-litigate.
- No `git push`, no edits to `oto/`/`tests/` by Class B, no `.env` edits
  by the operator.

## 11. What is still open

See §4.2 (owner-internal) and §4.1 (blocked). The most consequential:
- C4 gfx902 starter research (needs API key).
- C7.1 gfx902 profile (needs C4).
- CC:256/512 perf A/B (needs TTY).
- gfx90c tuning doc → caveman-full (not done).
- Rename plan implementation (proposal only).
- AGENTIC plan implementation (design doc only).

## 12. Verification commands

```
python3 -m oto doctor          # environment + toolchain + profile + registry + docs
python3 -m oto verify all      # evergreen equivalence across commits
python3 -m pytest -q            # full suite (1077 passed, 8 skipped)
python3 -m ruff check .         # pinned rule set
python3 -m oto check candidates  # deck gate-legal (280 checked, 0 illegal)
python3 -m oto check db          # registry integrity + contamination
python3 -m oto device derive     # print derived limits (no room for error)
```

## 13. File map (for the next agent)

- `oto/device/derive.py` — deterministic limits derivation
- `oto/device/loader.py` — resolve_profile choke point
- `oto/runners/toolchain.py` — explicit-env-or-fail contract
- `oto/cli/doctor.py` — full toolchain dashboard
- `oto/tensile/config_writer.py` — NumElementsToValidate=128, Architecture pin
- `oto/tensile/gates/*` — CPU legality gates
- `oto/harness/*` — analysis harness (read-only over corpus)
- `oto/ledger/*` — durable state + convergence state machine
- `oto/metrics/*` — measurements → verdicts/reports/status
- `oto/tensile/synthesis/*` — candidate synthesis (donor/narrow/wide/direction)
- `oto/tensile/decks.py` — family decks + KNOB_SWEEPS + PLAN_BATCH
- `oto/tensile/knob_surface.py` — forwarding surface (FORWARDED/NOT_FORWARDED)
- `oto/agents/*` — device-doc generators (agent-1/agent-2/meta)
- `docs/README.md` — docs ecosystem registry (class-tagged)
- `docs/operator_runbook.md` — Class B bring-up
- `docs/operator_campaign.md` — Class B tuning campaign (self-contained)
- `plans/` — slice plans (AGENTIC, CLI_UX, REFACTOR_2, test_optimization, RENAME)
- `.env` — user-provided toolchain (ROCM_PATH mandatory)
- `profiles/<codename>.json` — device data (the only place device facts live)
- `phases.yaml` — the candidate deck (280 rows, 0 illegal)
- `gfx90c_results/` — campaign artifacts (kernel_db, reports, libraries)
- `incomplete_work.md` — open items only
- `results.md` — measured evidence
- `potential_configs.md` — candidate deck + research history
- `changelog.md` — append-only evolution log
- `todo.txt` — user-only (agents MUST NOT read/touch)

## 14. The one rule that outlasts every other

**Measurement is the only argument.** No gate, no formula, no derived ceiling
is a benchmark. The CPU gates and the Tensile reference validator prove
legality; only a TTY benchmark proves performance. Every claim in this
project's docs is either measured (cite the run + kernel_db) or UNVERIFIED.
The operator agent's job is to produce evidence, not verdicts.
