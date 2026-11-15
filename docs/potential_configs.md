# Potential candidate configurations — how to derive a deck on a new target
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


> **TEMPLATE — copy and fill per device.** Do not edit the golden example; populate this file for your target.

> Device-independent methodology for turning a new target into a candidate
> deck, a gate set and an overnight run. This file is deliberately
> architecture-agnostic: no peak, budget, or cell verdict is written here.
> The worked example — every measured number, table, run id and verdict — is
> the gfx90c port, preserved whole in `docs/gfx90c_tuning_guide.md` §13
> (absorbed from this file's predecessor, which lived here through 2026-10 and
> was the port's working document). Read that section to see how the procedure
> lands on a real part; read this one to know how to run the procedure itself.
>
> Porting checklist for a new target (C4/C7.1): §11.
> A map from every former §-pointer of the old file to its new home: §10.

## 1. What a deck is

One row per (family, pattern, shape, tile, knob-set) candidate configuration.
The deck is the *allowed set*, nothing more. It is not a search strategy
(that is the routes and the ledger), it is not legality rationale (that is the
gates), and it is not evidence (that is `docs/gfx90c_results.md`). The deck only
reaches Tensile knobs the launch boundary actually forwards — a row carrying an
unforwarded knob silently measures the base tile under a name that claims
otherwise (see `oto/tensile/config_writer.py` `NOT_FORWARDED_KNOBS`).

Two rules govern every row:

- **Deck controls geometry and residency, not the pipe.** New instruction
  classes would need a design change, not a deck row.
- **Every row must be gate-legal on the target** (§3). A refused row is spent
  budget, not a finding.

## 2. The pipeline

```
synthesise (generator)  →  gate (CPU, preflight)  →  measure (GPU, TTY)  →  grade (A/B)  →  re-tune (next deck)
```

- **Synthesise** with `oto.harness.candidate_generator`; every emitted row is
  machine-checked (`--dry-run` reports drops/strips/refusals and exits
  non-zero on any).
- **Gate** with `oto check candidates` (deck) and `oto check candidates --floor`
  (the shipped floor manifest). The gate set is calibrated against Tensile's
  own verdicts — method in §3.6, worked example `docs/gfx90c_tuning_guide.md` §13 §R24.
- **Measure** in a TTY session only; the overnight procedure is §8.
- **Grade** with the like-for-like rule of §4 against the locked floor.
- **Re-tune** by rebuilding the kernel DB (`oto.harness.kernel_db --rebuild`),
  re-reading the ledger trace (§6) and editing the deck. Never re-propose a
  config already in the ledger; ban retired tiles explicitly.

## 3. The gates — what a legal candidate must pass

Every rule here was **calibrated, not assumed**: for each rule, the corpus was
re-scored and the rule counted its misses (built but refused) and false
rejections (refused but built). The gate set ships only when both populations
are 0 (worked example: `docs/gfx90c_tuning_guide.md` §13 §R24/§R23). On a new
target, expect every rule to need re-calibration.

### 3.1 Per-thread accumulator budget

`accVGPR = TT0 × TT1 × weight(dtype)` must fit the per-thread accumulator
budget derived from the register file width and measured from emitted code
objects. Necessary, **not sufficient**: it admits rows the workgroup rule
refuses (§3.2).

### 3.2 Per-workgroup register file (`overflowedResources`)

Tensile sets `overflowedResources = 4` when
`vgprPerThreadPerOccupancy = 65536 // NumThreads` and
`numWorkGroupsPerCU = vgprPerThreadPerOccupancy // max(vgpr, agpr)` is below 1.
The accumulator set is allocated in every kernel, so

```
weight × MT0 × MT1 × LocalSplitU >= 65536  →  refuse
```

is a sound lower bound independent of the measured VGPR total (ThreadTile
cancels out). Use `>=`, not `>`: a set that exactly fills the file leaves no
room for operands or addresses. (Worked example: `docs/gfx90c_tuning_guide.md` §13 §R24 rule 1, §R27.)

### 3.3 LDS tile budget

`(MT0 + MT1) × DepthU × bytes(LDS row) <= per-workgroup LDS budget`.
The per-device constant is a property of the part — re-derive it, never copy
it across devices. Keep the budget as Tensile's own `numBytes()` reads the
dtype (the complex-double Z case in the gfx90c port is the canonical
cautionary tale, case study §13 §9 D2 and guide §12.2).

### 3.4 Classic-load divisibility

- `MT0 × DepthU` and `MT1 × DepthU` must divide by `NumThreads × GLVW`.
- `GLVW` honours the 16-byte hardware cap; `NLCA` must divide `numLoads`,
  divide `totalVectorsCoalesced`, and leave `totalElementsPerp` divisible by
  `numLoads / NLCA` (`oto/tensile/gates/loads.py::_nlca_stage`).
- Watch for the pv-reduction no-op (`GLVW` unpaired, or `VectorWidth`
  cancelling it) — a legal-looking row can still be a silent base-tile rerun.

### 3.5 Assembly-class rules

Target-specific opcode legality (e.g. complex/half GSU > 1 on a part without
the corresponding instruction path). These belong in a CPU-only gate with a
regression test per rule.

### 3.6 The legality oracle — ask Tensile itself

The gate set cannot anticipate every refusal Tensile will emit. Build a small
probe set of known-legal and known-illegal configs, run Tensile's solution
construction on them, and treat the disagreement classes as gate bugs. Then
re-run the gate-closure measurement (`oto.harness.gate_calibration`) until
both populations read 0.

## 4. The measurement protocol — like-for-like or nothing

The cheapest way to lose a week is to compare two numbers measured under
different protocols. Four rules, all learned the hard way:

### 4.1 One client protocol per comparison

A **single-problem invocation** (1-row problem list, 8 back-to-back reps) and a
**family-protocol invocation** (5–8-row problem list, sleep-spaced, per seed)
differ by 1.6–4.2× on the *same config on the same client*. Never grade an arm
measured one way against a floor measured the other. Every headline number in
an acceptance report is labelled with its protocol, and the like-for-like
regrade is a first-class step of the port, not an optional audit (worked
example: §R50.1–§R50.4).

### 4.2 The tie band is a policy knob, not a measurement

State the band used (`tie_band_pct`) next to the corpus's measured
reproducibility band. A cell whose delta is smaller than the reproducibility
band cannot be *shown* to flip by another candidate — the lever there is
**replication** (more seeds → smaller band), not geometry.

### 4.3 Grade on a robust statistic

Grading on `max(raw sample)` is an order statistic: the arm that draws more
kernels wins more often. Grade the A/B on **rank-1 medians** (best-kernel per
cell, both arms, co-primary with `floor_best`), report the median for context,
and never let a max-of-draws verdict reach a report (worked
example: §R0).

### 4.4 Sweep order and clock hygiene

`ProblemSizes` are emitted in file order, and back-to-back runs on a throttled
clock re-measure the tail of one problem onto its successor — a lexicographic
defect once cost the CC:256 cell its verdict. Order problem lists
canonical-ascending, and where the instrument permits, record clock telemetry;
never widen a band to close a verdict.

## 5. Experiment order on a new target

Map the literature's order before spending GPU time. Suggested sequence
(mechanisms: `docs/research/kernel_tuning.md`, `docs/research/complex_gemm_brief.md`,
`docs/invariants.md`):

1. Small-shape band first — it is where a floor tuned for a big part loses by
   20–100 % and the gains are cheapest.
2. CPU predictor/ranking tool before any GPU launch (grid fill, tail, residency).
3. Independent sweeps of thread tile vs K-depth on the most binding dtype.
4. One pipeline knob at a time (prefetch, buffers, NT), verifying each is
   forwarded on the target before it is swept.
5. Split-K / Stream-K style routes only if the launch boundary forwards them;
   otherwise background them, never deck them.
6. Tie cells last, by replication, not by new candidates (§4.2).

## 6. Reading the ledger trace

`oto.harness.corpus_census` + `oto.harness.cell_resolver` fingerprint every
measured config's (family, shape, MacroTile, ThreadTile, VW, DepthU) and
report per-cell breadth. Two patterns predict wasted nights:

- **Flood** — hundreds of near-duplicate mutants of one config in a cell whose
  `median / winner` ratio is 0.2–0.3 (§13 §R7/§R0). Cap the population and mutate
  only active survivors.
- **Starvation** — cells unreachable by construction because a target-cell list
  or a family pattern is wrong (§R40 deck bugs). Audit the target-cell coverage
  table *before* the run, not after.

## 7. Axes the corpus has finished with

Close axes explicitly and record the closing measurement (worked example:
`§R41` — LDS pads, GlobalSplitU, StaggerU, NLCA, WGM 1/8, per-family tile
ceilings). Each closed row costs nothing to carry and prevents a night of dead
emitted rows. A closed axis re-opens only with new target-level evidence,
never because a deck author wants one more try.

## 8. The overnight run — rules of the road

CPU-only, safe anywhere:

```bash
<generator> --dry-run     # 0 drops, 0 strips, 0 refusals
<preflight tests>         # the port's own battery
```

TTY only, never under a full desktop compositor:

```bash
rocm-smi --showtemp --showpower     # confirm the GPU is actually there
<run> --budget <N>                  # the port's one long command
<probe the registry>                # status + abort_reason, immediately
ls <run dir>/core.*                 # must be 0
<read the A/B>                      # only after the above pass
```

If the run finalises `failed` with an `abort_reason` (GPU loss, consecutive
empty phases), stop: the night bought nothing and its configs must not be
re-used. If it reports `completed` with zero cores, the §4 protocol is the
scoreboard, and the replicate half and the real-gain half are read separately.

## 9. Open decisions

Any decision with no evidence yet (a byte-width table, a steal sanction, a band
width) is *user-owned*. The agent records the decision with its evidence and
its recommendation, and never acts on it silently. Resolutions are marked in
place with the date and the deciding party; the old record is never deleted.

## 10. Where everything went (former §-pointers)

The previous content of this file — the gfx90c working document, rewrites 1–8 —
was absorbed whole into `docs/gfx90c_tuning_guide.md` §13 with all R-numbers
preserved. `§14` (the prior-campaign autopsy) and `§15` (the corpus-pass audit
trail) are new sections folded in from `archive/` after the archive left git.
Resolution table for off-repo citations (git history, code comment
`potential_configs.md §…`, test docstrings):

| former pointer | now lives | what it carries |
|---|---|---|
| `…§R40`–`§R57` (rewrite 8) | tuning guide §13, subsections `### R40…` | geometry/R40 deck, R41 closed axes, R42 straggler classes, R43 routes, R44 legality, R45 batch, R46 agent questions, R47 re-derived stragglers, R48 orange triage, R50 protocol regrade, R51–R54 tracker/battles/decision, R55 TTY run, R56 triage/calibration, R57 last-fill |
| `…§R34`–`§R39` (rewrite 7) | same file, `### R34…` | the failed-overnight post-mortem, the void virgin-generation read, the 18 tie cells, the tied-cell deck, the honest reading of the next A/B, preflight/post-run |
| `…§R24`–`§R33` (rewrite 6) | same file, `### R24…` | gate closure (0/0), the tie taxonomy, the straggler tracker, the provable tile ceilings, the ledger trace, kernel-type patterns, the deck changes, stop-list, the overnight command, literature-mapped order |
| `…§R16`–`§R23` (rewrite 5) | same file, `### R16…` | the forwarding surface, tie taxonomy (19/19), adaptation routes, deck changes, launch-boundary, failed-candidate triage, the two refusing gates |
| `…§R10`–`§R15` (rewrite 4) | same file, `### R10…` | the 2026-10-16 A/B audit, hardware read, route updates, stop-list, concrete deck |
| `…`Revision 3` (`§R0`–`§R6`) | same file, `#### R0…` | verdict basis, attribution bug, ORANGE artefact, hardware read, floor census, SOTA low-tier, mutator domain flaws |
| `…`Rewrite 2` (`§R7`–`§R9`) | same file, `#### R7…` | deck-flood fix, newly ranked levers, Route G (the CC steal) with its port record |
| `…§1`–`§8` (rewrite 1) | same file, `### 1. Executive…` | five findings, per-family tie causes, occupancy settlement, kernel-type patterns, complex physics, routes A–F, stop-list, concrete deck additions (§8.1 legality matrix, §8.2 never-generated tiles) |
| `…§9` (open decisions D1–D4) | same file, `### 9. Open decisions…` | sweep-order, Z byte width, ZZ-deck re-check, paired widen |
| `…§10`–`§11` (GUI prep, runbook) | same file, `### 10. GUI-safe prep…` / `### 11. …` | the 10+ h overnight protocol as it stood on 2026-10-16 |
| `…`F1`–`F5` (findings) | same file, inside `### 1. Executive…` | spoof-floor telemetry, never-varied knobs, narrowness of CC/ZZ, occupancy read, the FMA-roof correction |
| `…Sources` | same file, `### Sources` | the evidence chain |
| `…§14.5` (spoof-steal) | same file, `### R8…` (rewrite 2) + `## 6. The routes…` | steal rules and the port record |

New citations should reference the tuning guide directly.

## 11. Porting checklist to a new target

1. **Profile**: device JSON + re-derive peaks from first principles (do not
   inherit them from another part).
2. **VGPR model**: run the measurement harness on the target's emitted code
   objects; rebuild the tables; keep gate calibration at 0/0.
3. **LDS byte model**: re-derive `numBytes()` table from the target's Tensile
   checkout; the Z row is the classic trap.
4. **Peaks & ceilings**: re-measure or derive from the ALU graph; set the bar
   in the report tool; never reuse another target's bar.
5. **Corpus build**: generate a target-legal seed corpus; a first A/B from
   cold start will not beat a mature library — budget accordingly.
6. **Like-for-like**: regrade every headline verdict under one protocol before
   claiming anything (§4).
7. **Drift manifest**: re-attest every floating attestation at the new HEAD.
8. **Agent route**: if using `oto agent consult`, ingest the starter profile
   and let the agent synthesis emit the per-device docs; this file stays the
   methodology, the per-device outputs stay in that device's docs directory.
