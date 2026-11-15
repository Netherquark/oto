# gfx90c — oto Port Design Brief

The compact statement of what oto is for and how it behaves. The normative
contract lives in `docs/search_philosophy.md`; this file is the short-form
summary for a reader who needs the framing in one screen. It is not a
checklist, a roadmap, or an issue tracker; the live campaign status lives in
`docs/results.md` and `incomplete_work.md`.

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

## Port mechanics (current)

The driver runs the shipped plan end to end: manifest → candidate deck →
correctness → full-suite benchmark → evaluate at the deterministic winner
policy → harvest wins / mutate ≤2 knobs / tie. The fluid baseline (same-run,
same-form) reads parity; everything else is in progress, not done. The
footprint, the visibility, the gate, and the verdict are all live and
measured under this contract.

## What this is NOT

- **Not LLM-in-the-loop.** The model proposes parameter vectors only;
  Tensile generates; the compiler validates; the hardware decides. The model
  does not decide correctness, perf, or verdicts.
- **Not probabilistic.** Every phase is deterministic by construction: a config
  either benches green or refuses. No search gate, no heuristic tuning inside
  the driver's static sweep.
- **Not a fairness contest between libraries.** The reference floor is a
  baseline, not a target to merely match; verdicts against the floor are WIN
  / TIE / LOSS relative to that floor. Above it, the acceptance bar is the
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
