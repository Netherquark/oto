# oto — Design Brief
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


The compact statement of what oto is for and how it behaves. The normative
contract for the driver's acceptance path lives in `docs/search_philosophy.md`;
the agentic layer's design lives in `docs/agentic_consult.md`; measured status
lives in `docs/gfx90c_results.md` and `incomplete_work.md`. This file is the short
framing, kept honest about **what exists today and what does not**.

## Objective

Produce an optimal Tensile library for the gfx90c iGPU in Ryzen 5 5650U
(Vega 10 window, 7 active Compute Units, wave-64, no MFMA), matching the bar
AMD never shipped. Two standing bars:

1. **Footprint parity** — the 38 (family, shape) cells in
   `docs/shipped_floor_contract.md` must each carry a native gfx90c kernel; the
   floor is the reference library.
2. **Approach the theoretical limit** — the per-family roofs in
   `docs/gfx90c_theoretical_limits.md`. Verdicts compare against that authority,
   medial-of-seeds + clock-normalised.

## How oto is built — two loops, one rule

**The inner loop (the acceptance path) is deterministic, and stays that way.**
manifest → candidate deck → correctness → benchmark → deterministic winner
policy → harvest / mutate ≤2 knobs / tie. Given the deck, the driver is
repeatable: a config either benches green or refuses, and no probabilistic
gate, heuristic tuner, or model sits inside it. Correctness is decided by
Tensile's builds and the hardware, never by a model; verdicts are computed
from medians-of-seeds by policy code. `docs/search_philosophy.md` is the
contract for this loop, and the LLM has no role in it.

**The outer layer (which configs go on the deck) is LLM-assisted and ships
today.** The `oto/agents` package carries exactly this layer:

- **agent-1** (`oto/agents/theoretical_limits.py`) drafts the per-device
  theoretical-limits doc; **agent-2** (`oto/agents/tuning_context.py`) drafts
  the tuning context, with directed prompts that require ISA-manual citations.
- **oto agent consult** (`oto/agents/census_consult.py`, shipped) ingests a
  starter file + a device profile + the local corpus and emits
  `<codename>_docs/potential_configs.md` with gate-legal rows, corpus priors,
  rejection taxa, and a TTY to-do list — CPU-only.
- The directed research corpus (`oto agent generate`) is LLM-drafted, draft
  only; `docs/agentic_consult.md` marks precisely which parts are *shipped*
  vs *design* (the GPU proof, `OTO_AGENT_ALL`, `--full`, `--trials-per-family`
  have no code).

The rule both loops share: **the model proposes, never decides.** Every
proposal — a drafted doc, a suggested config, a research claim — passes the
CPU gates and the GPU measurement before it becomes a verdict. The gfx90c port
itself was built this way (class-A LLM-in-the-loop development with human
review, plus the deterministic driver for everything measured).

## What this is NOT

- **Not autonomous end-to-end, yet.** `oto agent consult` is CPU-only; the
  end-to-end run for a new device (gfx902: agent consult → GPU proof →
  best-effort library) is assembled in design and blocked on the owner's API
  key. Nobody should read this repo as claiming an autonomy that is not built.
- **Not probabilistic at the acceptance boundary.** Inside the driver, given a
  deck, every phase is deterministic by construction. Variance enters as
  measurement noise (handled by seeds, medians, CV gates), never as an
  algorithmic coin flip.
- **Not a fairness contest between libraries.** The reference floor is a
  baseline, not a target to merely match; verdicts against the floor are WIN /
  TIE / LOSS relative to that floor. Above it, the acceptance bar is the
  theoretical roofs.

## Measurement discipline

- Winner = **median-of-seeds** (`NumBenchmarks >= 3`); max is reference only.
- Comparisons = **throttle-adjusted** per (datatype, bound_class); the sclk-ruler
  requires ≥10 samples and median busy>0; missing controls are reported, never
  guessed.
- Retirement is the evidence-gated single Tier-2 path
  (`oto/metrics/cell_policy.check_retirement_eligibility`); the floor is never
  a retirement signal.
- The accepted ceiling set lives in `docs/gfx90c_theoretical_limits.md`; the
  acceptance report carries those ceilings alongside verdicts.
