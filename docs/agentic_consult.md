# Agentic consult — automated potential_configs synthesis

Class A (developer) — the design for automating `potential_configs.md` generation
for a new device, from a starter file + an API key, with the least possible GPU
work. This document is the implementation plan. It is not implemented yet; it is
the specification that turns the gfx90c campaign's hard-won method into a
procedure the tool can follow end to end.

## §0. The goal, in one sentence

Given a starter file for a GPU that oto has never seen, plus an LLM API key,
oto ingests both and emits a finished `potential_configs.md` — a candidate
deck, ranked, with evidence, and a `phases.yaml` continuation — without a human
in the loop and without benchmarks it does not need.

## §1. The problem as it currently stands

Today `oto agent generate` runs agent-1 (theoretical limits) and agent-2
(tuning context) plus an optional CPU-only harness study and then writes the
three device docs beside the repo root. It does **not** produce the missing
half: the *concrete candidate deck* with evidence and a least-GPU-trial
strategy. The gfx90c campaign got to 19 W / 19 T / 0 L with roughly four dozen
measured cells out of an 1101-row seed, of which only ~280 were ever measured
and ~180 of those were measured cells. Reproducing that ratio for a new device
by replaying the full deck end-to-end wastes most of it. This plan automates
the funnel instead: from profile facts → cheap CPU gate drops → Tensile probe
→ a small GPU shortlist → convergence — and writes the result as the device's
`potential_configs.md`.

`potential_configs.md` is the device-tuned deliverable. Everything else — the
limits doc, the tuning context, the harness study, the report — is scaffolding
for it.

## §2. What the gfx90c campaign actually did (the evidence this plan encodes)

Every stage below existed, in some form, during the gfx90c port. The plan is
not speculative; it is a codification.

1. **Floor discovery from the installed TensileLibrary** — the shipped gfx900
   manifest gave 2,285 kernels across 28 families; the *footprint contract*
   (`docs/shipped_floor_contract.md`) cut to 1,027 candidate rows from the
   floor's own winning config captures. In launchable form the deck was
   ~493 numeric measurements + ~60 builder probes. The lesson: the floor's
   winners are the *easiest-to-vet* starting candidates — the vendor already
   measured them for its own silicon family. Rating unknowns first, then the
   small delta hunt, is where the time goes.
2. **Wave-quantization first** (small cells, 0.25–0.30 residency) — the
   largest-win region in the corpus. Automatable as a family-tag heuristic:
   cells where grid tiles < 14 get the "wavefill" treatment by default.
3. **CPU-side gate pruning** — the launch gates (`validate_config` +
   `ldspad_feasible` + `ldtile` + the vendored `vgpr_model`) drop >90% of the
   raw candidate set before any Tensile probe. The reference flow needs this
   or it dies on weeks of builds that produce nothing.
4. **Tensile oracle probing** — `oto.harness.deck_probe` / `tensile_probe`
   ask Tensile itself whether the remaining configs build (CPU-only). This is
   the big new step the gfx90c work surfaced after adding
   `NumElementsToValidate=128`: Tensile's own CI validator now refuses illegal
   kernels at build time, and "builds or does not build" is nearly free
   evidence compared to a runtime benchmark.
5. **Small-scale benchmark funnel** — the campaign measured ~280 deck + ~60
   floor cells and produced 19 WIN / 19 TIE / 0 LOSS against the gfx900 floor.
   The whole gfx90c campaign is reducible to: ~60 benchmark runs × ~83 s ≈ 1.4
   GPU-hours for the complete corpus study, outputting the entire
   `potential_configs.md` with per-cell winners, ties, losses, and reasons.
6. **Perspectives from the report** — `oto report` ingests the benchmark DB
   and writes the verdict JSON/HTML; the report's family coverage and
   red/orange/tie splits already map directly onto `potential_configs.md`'s
   sections (§R numbers were transcribed from these verdicts hour by hour).
7. **The output format itself is the trick** — `potential_configs.md` is not
   a benchmark dump. It is: the deck's candidate sources named by family with
   fingerprint + tile geometry; one row per (family, shape, config); the
   median-of-seeds velocity; the knob delta between native winner and floor
   winner; a per-family narrative with the one thing that mattered; the
   retrospectives section keyed to RSM/REX rules. None of that structure
   exists in the codebase today. The plan separates "measure" from
   "synthesise potential_configs.md" — the synthesis is templated and owned by
   the agent layer, not the harness.

## §3. What the plan requires of the codebase

### §3.1 `oto/agents/potential_configs.py` (new)

The orchestration entry: `generate(profile, base_dir, research=None,
harness=None)` returning a dict of synthesised artifacts (which docs and
overlay files were written). Owns: the stage order, the dependency graph,
and the never-return-an-incomplete-result-while-leaving-a-dead-file rule.
Does NOT own: content generation (agents do), stage semantics, scoring.
`oto agent generate` becomes this module when `OTO_AGENT_ALL=1` is set or
`--full` is passed (§§5–8 ship as a single opt-in today; splitting it into
selectable stages is deliberate).

Pipeline:

```
starter file
  → load_profile_from_starter(load_profile=True)          [existing]
  → research_client.make_researcher(starter_text=text)    [existing]
  → agent-1 (theoretical_limits.md), agent-2 (tuning_context.md) [existing]
  → harness study (kernel_db/corpus_census/candidate_rows) [existing]
  → candidate deck (family_decks.build_seed + probe)         [enlarged]
  → deck_pin (fingerprint all candidates)                    [new stage]
  → oracle_filter (Tensile build probe, CPU-only)            [new stage]
  → sweep_size_guesser (GPU-trial count per family)          [new]
  → retune loop (`oto tune` with a narrow deck, TTY)         [existing]
  → report (`oto report`)                                     [existing]
  → potential_configs.md synthesis (the new export)           [new]
```

### §3.2 Stage: candidate pin & oracle filter

Given the emitted deck (be it ~2k rows, or an emptiness-pruned one), annotate
each row with: fingerprint, family, wave-per-CU, and per-family risk class
(grid fill < 0.25 for small cells on 7-CU grids). Drop the rows that
`validate_config` already vetoes — the gfx90c campaign showed those are almost
all catalog-floor rejects. Budget: zero GPU time.

Next, build the remaining rows through Tensile's own kernel writer (M =
`NumElementsToValidate`), record which ones Tensile accepts silently vs
rejects with a real error message. This is `oto run_probes` (new verb or a
`--probe` flag on `oto check tensile-build`). Track the results in the
registry (`mark_phase_probe`); any row Tensile refused goes out without ever
touching the GPU. Track 0-GPU cost; it delays nothing.

### §3.3 Stage: funnel size per family

Each family gets a benchmark budget (`--trials-per-family`, default 8,
overridable by a header line in the starter). The sweep pattern ordered by
expected value is:

1. Wavefill refill: small tiles + GlobalSplitU for <0.25 residency cells (this
   was 3/19 of the gfx90c family).
2. Ceiling search: TILE(SweepStep, 64, family_shapes) ∈ {128x128, 128×64,
   64x64} for the small cubes, 1024+, direct-lookup reuse (nothing new to
   measure there except padding 1 improvement).
3. xf16/native-f16 reuse for the HPA families: 32-bit loads only — HPA unreachable on GCN.

For each trial the funnel records (measure, retune, report); the engine sees
the delta from the *same cell's first measurement* (native vs best-so-far),
so until a measurement lands the loop plans no further cells in that family.

### §3.4 Stage: potential_configs synthesis

`oto/agents/potential_configs_export.py` builds the markdown from the DB and
the report:

- §A. Bounds: per-family paragraphs mirroring the gfx90c structure,
  with per-family tile counts, unsupported-vs-accepted verdict, and the
  "why this GPU is different" note (APU/CPU-shared-L2 vs GFX).
- §B. Per-family coverage: the exact tile shape that won and the
  per-cell native-vs-floor delta — no screenshots, just numbers.
- §C. Unsupported: the family's tile/lattice rejection evidence. Zero claims
  without proof, or the section does not exist.
- §D. Winners: the six bullets per family that matter, each with a proof
  pointer (run id + report path).
- §E. Wasted time: what we measured that nothing needed; catalogue of
  dead avenues (split-complex? DB? GSU?) tied to the probe results.
- §F. Open work: what is still unknown, with the guessing game called out
  (if you guess, say so).

The export is byte-compiled, not generated by str.join — isinstance checks +
assert all placeholders resolved before write. The `oto library best-effort`
output (.dat path + manifest) is appended at §H.

### §3.5 `oto doctor`

New checks: `research_key` (source: starter|env|missing — never prints the
key), `deck_ready`, `probe_complete`. Log file always exists at
`oto_<phase>.log` under the run dir — gitignored with the rest of runtime
logs.

## §4. The API key contract

The starter file carries the key in a single line:

```
api_key: <value>
```

If the value begins with `$`, it is expanded against the environment
(`api_key: $OUTSOMEKEY`). If the environment has it already (OTO_API_KEY,
ANTHROPIC_API_KEY, OPENAI_API_KEY), the starter line is irrelevant. If both
are absent, the campaign proceeds with empty research (the doc agents emit the
warning header: "UNVERIFIED — key absent; no claims beyond first-party
documents" at the top of every generated doc). Keys are never:

- printed (log only last 4 chars + "<redacted>");
- written to any file, nor serialized into any doc;
- committed to the repo (the starter files are user-local; the starter parser
  never writes api_key into anything derived).

`oto doctor` reports `research_key: starter|env|absent` and never the value.
`tests/test_research_key.py` under-covers this forever: it is the test that
should be impossible to write wrongly.

## §5. What the operator does

```
# 1. starter file
cat > my_gpu_starter.md <<'START'
codename: gfx10xx
isa: [10,0,0]
num_cus: 4
...
api_key: $MY_KEY
START

# 2. one command, from repo root, GPU in TTY
python3 -m oto agent generate my_gpu_starter.md --full

# 3. read the report, commit the doc, done
oto report
```

Files emitted:

- `<codename>_theoretical_limits.md` — agent-1 output
- `<codename>_tuning_context.md` — agent-2 output
- `<codename>_harness_study.md` — CPU-only harness study
- `potential_configs.md` — the deliverable
- `<codename>_results/` — probe logs, report HTML, best-effort `.dat`

## §6. The acceptance test

Plan is done when a fresh Ryzen AI 9 HX 370 iGPU profile generated by this
flow, fed through an isolated TTY campaign, produces a deck with outcomes
within 2 WIN of the gfx90c reference deck (the LASSO-TLU deck: the parent
family's fundamental tile axis that does not move on any GCN5-class part,
measured end-to-end on this part). That is a real benchmark comparison with
real nulls, not a paper claim.

If it produces 12 WIN / 14 TIE / 12 LOSS against that baseline, the flow is
correct; the LOSS column just becomes the family retry list for the next
campaign.

## §7. What deliberately stays out

- The GPU benchmark pass itself (`oto tune`) is not automated here. It is the
  one step an operator must drive, because TTY/GPU discipline is a human
  contract, not a loop invariant.
- The API research corpus is never trusted. Agent-1/agent-2 drafts are
  UNVERIFIED; only first-party sources (vendor datasheets, ISA manuals,
  Tensile source) close a claim. The pipeline forces that with the same rule
  as the compile gate: unverified-by-first-party goes out unmarked, never as
  fact.
- Fresh-deck legality is always re-proved on the target, never transcribed
  from gfx90c. The 7-CU restriction is a GCN5 position, not a law.

## §8. Where this touches the tree

| Path | Role |
|---|---|
| `oto/agents/potential_configs.py` | the orchestrator (new) |
| `oto/agents/potential_configs_export.py` | the export renderer (new) |
| `oto/cli/commands.py`, `oto/cli/parser.py` | `--full` flag on `oto agent generate` |
| `oto/tools/probe_builds.py` | the probe stage (new; CPU-only; writes the registry) |
| `oto/metrics/potential_configs.py` | the export helpers (new) |
| `tests/test_agent_generate_full.py` | the acceptance test (new) |
| `docs/operator_runbook.md` | a pointer to this file as the Class B entry for new-device docks |
