# Measured evidence — template (populated by the agent per device)

> **Status: TEMPLATE, NOT POPULATED.** This file ships with the repository as
> device-independent scaffolding. It becomes a real document only when an
> agent on a new target has run real benchmarks and fills it in honestly.
> Until then it says only what belongs here and how it gets here.
>
> The gfx90c port's measured record lives in `docs/gfx90c_results.md` — consult
> it as a golden reference / worked example **only if needed**, and never copy
> its numbers as evidence for another device; those numbers belong to that
> machine, that library, that day. Reproduce, don't transplant.

## 1. What this file is (and is not)

This is the per-port home of measured A/B evidence: scoreboard, per-cell
verdicts, gate census, the clock discipline behind the numbers. It is *not* the
ceiling authority (that is `docs/<codename>_theoretical_limits.md`, filled the
same way from the generic `docs/theoretical_limits.md` template), and it is *not*
the candidate deck (`docs/potential_configs.md`'s worked example is the gfx90c
case study in `docs/gfx90c_tuning_guide.md` §13).

## 2. How the agent populates it — the order is load-bearing

1. Run an A/B on the target in a TTY session (never from a desktop/GUI session):
   native vs locked floor, `NumBenchmarks ≥ 3`, `SleepPercent`-sized phases.
2. Rebuild the corpus view before quoting anything:
   `python3 -m oto.harness.kernel_db --rebuild`
3. Re-read coverage and triage:
   `python3 -m oto.harness.cell_resolver --taxonomy`
4. Read the like-for-like report — both arms under the **same protocol**
   (`oto report --json` / `oto report --html`; see `docs/comparability.md` for
   the admission rule). State the tie band you used and the measured
   reproducibility band beside it; a verdict without both is not a verdict.
5. Fill in §3 below. Delete nothing that was true; append; supersede with new
   dates, never edit history away.

## 3. Required sections on completion

- **Scoreboard** — date, run id, phases, budget, GPU-time, TOC status
  (`rocm-smi`), protocol (family vs single-problem — never mixed), tie band,
  verdicts (WIN/TIE/LOSS/RED/ORANGE), 0 RED cells.
- **Per-cell table** — family, shape, native, floor, delta, verdict,
  median-of-seeds spread, which arm was measured under which protocol.
- **Gate census** — misses vs false rejections on this target's corpus;
  the gate set ships only at 0/0 (see the gfx90c case study §13 for the shape
  of that measurement, `oto.harness.gate_calibration`).
- **Straggler classes** — which cells are stuck, why (typed, with the number
  that shows it), and what work each class requires.
- **Clock/thermal discipline** — telemetry coverage, sclk-ruler medians, the
  sweep-order defect check (`docs/gfx90c_results.md` §13.4 documents the
  2026-10-15 instance of this bug).

## 4. Hard rules for whoever fills this in

- **No perf claim without TTY evidence.** "Measured on gfx90c" requires a TU run
  on gfx90c; otherwise it goes in as a plan, not a result.
- **Like-for-like only** — one protocol per comparison; never grade a floor
  measured one way against candidates measured the other.
- **Median-of-seeds**, never max-of-seeds; report spread, not one lucky draw.
- **Cite the artifacts** (run ids, report files, gate census counters), not
  memory.
- GPUs are for the owner's TTY sessions; a subagent or overnight run does not
  loosen any rule here.

## 5. When this file is empty

It stays empty by default. Empty means "no device has been measured and this
file was never filled in", nothing more. The gfx90c golden example:
`docs/gfx90c_results.md`. Instructions for a new target: `docs/starter_pair.md`,
then the operator campaign (`docs/operator_campaign.md`).
