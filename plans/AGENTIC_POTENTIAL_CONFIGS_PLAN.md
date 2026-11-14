# AGENTIC_POTENTIAL_CONFIGS_PLAN — Automated consultation → final `potential_configs.md`

**Status:** proposed; not implemented.
**Owner:** the agent harness (`oto.agents.meta`), the gates (`oto/tensile/gates/*`),
the harness toolkit (`oto/agents/harness_tools.py`) and the two doc agents
(agent-1 `theoretical_limits.md`, agent-2 `tuning_context.md`).
**Goal.** Given (a) a starter file for a GPU, (b) an API key, produce the
`potential_configs.md` a senior tuning engineer would write for that device —
with the **fewest plausible GPU trial runs**, i.e. only the candidates the
kernel-selection evidence says are worth one.

This document formalizes the design so it can be implemented without re-deriving
the reasoning during the implementation itself. It is not a specification of
work to do *today*; it is the plan that the next implementation push follows.

---

## 1. What exists today

| piece | file | state |
|---|---|---|
| Agent-1 (ceilings doc) | `oto/agents/theoretical_limits.py` | landed; used by `oto agent generate` |
| Agent-2 (tuning context doc) | `oto/agents/tuning_context.py` | landed; gated on agent-1 output |
| Harness tools (CPU census, gap analysis, candidate proposals, gate verification, harness study) | `oto/agents/harness_tools.py` | landed (`oto/library best-effort` uses the census path) |
| Candidate enumeration | `oto/tensile/knob_sweep.py` + `oto/harness/_rows_core.py` | landed; emit and validate; GPU trial rows are scoped shapes |
| CPU gates | `oto/tensile/gates/assembly.py`, `ldspad_gate.py`, `occupancy.py`, `loads.py`, `vgpr_model.py` | landed; every gate is called at launch boundary and by the sweep tools |
| Coverage census | `oto/harness/corpus_census.py` | landed |
| Kernel database | `oto/harness/kernel_db.py` | landed; rebuilt from runs, carries per-row winners |
| `oto agent generate` CLI verb | `oto/cli/commands.py` (`agent generate`) | landed |
| API-key-driven research | `oto/agents/research.py` | landed; receives the starter+context, returns text |

### 1.1 What is missing

There is no automated consult that consumes that apparatus and emits the
**final** `potential_configs.md` for a new device, i.e. no phase-3 consult that
turns: corpus census + gate verdicts + starter-facts + prior runs into one doc.
Today an operator writes it by hand from `results.md` +
`potential_configs.md` + `gfx90c_tuning_guide.md` — hours of reading, and a
known footgun: it is easy to copy conclusions across devices (e.g. assuming
CC:256 needs AF4/4 because it helps gfx90c, when it may not on a different
part).

## 2. The contract for the output

The consult must produce, for a starter GPU (e.g. `gfx902`), one document that
carries:

1. **What the device is.** Vendor, marketing name, gfx codename, ALU/VALU/FMA
   instruction-set character, CU count, clocks, L2 size, LDS, shared-vs-
   discrete memory model, DP4A/MFMA availability, the profiling/runner stack it
   will be tuned on.
2. **The ceilings and the bars.** Practical ceilings per family (like
   `gfx90c_theoretical_limits.md`'s §5), derived from measured arithmetic —not
   from marketing FP32 peak.
3. **The rejection taxa.** Which geometry/axis/pair class is *structurally*
   forbidden on this device (e.g. GSU>1 for complex on no-MFMA parts), so a
   trial row for that class never reaches the GPU.
4. **The selected deck.** Per family, the candidate tile ladder and which of
   them are winners-but-ungenerated (i.e. candidates for first measurement).

In MDE terms this is the same work the gfx90c tune did, folded into one
document instead of five — but produced by the pipeline that already exists.

## 3. The flow ("one shot")

    starter.{md,json} + API-key
        |
        v
    [phase 0: environment + profile load -- no network, CPU only]
        |
        v
    [phase 1: agent-1 (theoretical limits)  -- API call]
        |
        v
    [phase 2: agent-2 (tuning context)       -- API call]
        |
        v
    [phase 3: CENSUS_CONSULT -- the new consult]
        |
        v
    <potentially docs/<codename>_potential_configs.md>

`CENSUS_CONSULT` is the heart of the proposal: it reads what the pipeline has
**already measured** for a different device and projects what it is safe to
try here. That requires no new GPU legs before the first trial run.

Inputs:

* `<codename>_starter.{md,json}` — the starter, with the target customer/ SKU
  and objective.
* `oto/device/<profile>` — accepts starter JSON as profile candidate.
* The local run corpus — every `run_*/` on disk, plus `kernel_db.json`.

Actions:

1. For each family: for each cell, retrieve from `kernel_db.json` winners and
   see whether the winner tile for this cell on a reference device maps
   (via `TARGET_CELLS` geometries) to a legal tile on the target; store the
   pass/fail per-axis verdict with the reason.
2. From the reference corpus census (axes census: `Tile/VW/DU/WGM/LdsPad/…`),
   derive which axes *moved* cells vs which did not on the reference device.
   Mark each axis `{measured-moving | measured-neutral | unmeasured}` for each
   family. This is the least-trial-runs lever: do not retry neutral axes blindly.
3. Emit, per family, a ranked list of candidate rows (like the R8 rows),
   scored by the census — plus the reasons they are unlikely to be windows
   (e.g. `CC:256 needs GSU=2 but no MFMA` → discard immediately).
4. Gate-run each candidate through `validate_config` + `occupancy_feasible` +
   `ldspad_feasible` (CPU-only). The output of the consult is **not allowed
   to contain any gate-refused row**.
5. Write the consult as `docs/<codename>_potential_configs.md` (overlay over
   the template), leaving `[FIGURE-TODO]` markers where the result matrix
   should land after the TTY run.

## 4. Least-trial-runs: the gfx90c precedent

From the gfx90c corpus walk, roughly:

* Only **one family** (SS) ever produced ≥ 2× shifts from candidate kernels
  once the floor had been beaten. Everything else moved < 15%.
* Per-knob acceptance from the census: `LdsPad`/`StaggerU` (LDS padding) gave
  real wins on CC/ZZ (one tile class, two groups of cells); `UseSgprForGRO`
  won on SD/HH classes; `GSU>1` wons on SS at 2048/4096; `AssertFree*` was
  unproven until the SGEMM-style recipe was re-emitted and GPU-validated.

So the consult for a new device whose ALU shape matches gfx90c's (≥ 56 VALU
lanes/CU, no MFMA, GCN5) should:

* Emit, per family, a **fixed tile config + one knob delta per row**.
* Cap the candidate count at ~25 per cell (the 2026-10-19 floor runs took
  14–25; the floor is the reference for "cheap and useful").
* Propose only deltas with at least one precedent in the corpus — never a
  delta that was never measured.

For a device whose instruction set differs (e.g. gfx110x style, packed BF16,
or gfx1201 MFMA), the census still applies but the premise shifts; the
diagnostics (which family, which axis moved) must be re-read from the target
device's own corpus, which does not exist yet — in that case the consult must
lower the claim to "best guess from the closest comparable device", cite that,
and never claim measurement.

## 5. API-key and safety policy

* The consult reads `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`OTO_API_KEY` the
  same way as today (`oto/agents/research.py` already picks + invokes).
* The API key is **never** written into the doc, log, or commit message.
* The consult must not write outside the output doc path; every other path
  is read-only.
* If the API key is missing, the consult exits cleanly with instructions, not
  partial output.
* If the API call fails, the doc carries the failed status; the chain stops
  there rather than emitting a half-baked consult.

## 6. What the implementation consumes (no new deps)

* stdlib only; existing `yaml`, `requests`, `dotenv`
* the gates in `oto/tensile/gates/`
* the harness tools in `oto/agents/harness_tools.py`
* the agent-1/2 pipeline in `oto/agents/`

No new dependency invented for this consult; the same ones the rest of
`oto agent generate` uses.

## 7. Test strategy (writes nothing to the registry)

* Unit tests: a synthetic profile (codename `testpipelinegpu`, replacing the
  gfx90c facts) feeds the consult; the output doc is verified against the
  gates for zero false-positives and zero false-negatives on the
  `validation-square` probe set.
* Integration test: run the consult over the gfx90c corpus, check that it
  produces a doc whose rows are all gate-legal; check the doc carries the
  `[FIGURE-TODO]` markers and no fabricated results.
* No test reads from a live GPU or a live API key — those stay env-gated
  (skip unless `OTO_RUN_API_TESTS=1`).

## 8. Rollout plan

1. Phase A (CPU only, ~2 days): census wrapper + `graph_candidate_rows`
   reuse; unit tests with synthetic profile; emit doc shape; verify gates.
2. Phase B (adds the API): wire agent-1/agent-2 outputs into the doc;
   `oto agent consult` CLI verb; integration test with synthetic profile.
3. Phase C (GPU proof): run the gfx90c consult; TTY run the emitted rows
   (TZ: small budget — 14–25 attempts per cell); ledger the results; update
   the doc with measured verdicts, closing the `[FIGURE-TODO]` markers.
4. Phase D: swap in `gfx902` consult; the human verifies hardware facts
   against first-party sources, then locks the profile; consult becomes the
   standard on-ramp for any new device target.

## 9. Non-goals

* This is not a replacement for the TTY perf run. No legality claim or perf
  claim becomes "verified" without TTY measurement; the doc always says which
  is which.
* This is not a marketing claim generator. If the consult fails, the doc says
  so; the chain does not fabricate benchmark numbers.
* This does not change any gfx90c artifact. It will be tested against the
  gfx90c corpus but the gfx90c output doc for this device is a separate
  deliverable, done by the human with the device on the desk.

## 10. Open questions for the owner

1. API provider preference (Anthropic / OpenAI / OTO_API_ENDPOINT)?
2. Budget per consult (token cost)?
3. Whether `oto agent consult` is the command name or folds into
   `oto agent generate`.
4. Where the emitted doc lives: `docs/<codename>_potential_configs.md` (this
   repo) or the target device's own repo?
5. Whether the consult is allowed to pick GPU launches without explicit
   human approval per launch, or only emits a plan for the human to execute.
