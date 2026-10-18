# Candidate deck for the gfx90c Vega-7 port — rewrite 6 (2026-10-18)

Supersedes rewrite 5 (R16–R23, kept below for history). **What is new here:** the
legality gate is now **closed** on our corpus — 0 misses, 0 false rejections, was
53 misses — from three rules calibrated in §R24; the tile axes now have
**provable ceilings** and the "wider MacroTile" route is **dead for CC and ZZ**
(§R27); the straggler list is decomposed into four classes with a per-class route
set (§R26), including why **no steal is justified**; the ledger trace per cell is
in §R28; and the deck's dead complex rows are replaced with the widest *legal*
tiles (§R30).

**Owns:** the candidate deck, the routes, the search rules, and the reading of the
gates. Does not own: ceilings and verdict bars
(`gfx90c_theoretical_limits.md` §5), measured evidence (`results.md`), hardware
facts (`gfx90c_theoretical_limits.md` §1–§3), the per-cell winners
(`gfx90c_results/analysis/cells_resolved.full.txt`), or the durable Tensile
mechanics (`kernel_tuning_research.md` §4).

---

## R24 — the latest A/B, and the gate is now closed

**Scoreboard.** `gfx90c_results/acceptance_report.json` (2026-10-18T09:53):
`run_20261018_004835` vs the locked floor `gfx900_ref_locked_52149f315d` →
**20 WIN / 18 TIE / 0 LOSS**, 0 RED / 12 ORANGE, 9 h 03 m. The report is
*provisional*: the gfx900 reference chain did not finish and the user declined a
re-measurement, so the verdicts are indicative. `CC:256` upgraded TIE → **WIN
(+7.8 %)** since `run_20261017_092909` — that is the CC steal (R8) landing.

**The gate is closed.** `python3 -m oto.harness.gate_calibration --population ours`:

| revision | phases | built | gate-refused | agreed | MISS | FALSE REJECTION |
|---|---|---|---|---|---|---|
| rewrite 5 | 3349 | 3217 | 79 | 79 | **53** | 0 |
| **now** | 3349 | 3217 | 132 | **132** | **0** | **0** |

Every native phase Tensile built, the gate allows; every phase the gate refuses,
Tensile did not build. 0 false rejections on *both* populations (ours, and the
3870 built reference phases). The three rules that closed it — each a
0-false-rejection fix:

**(1) The workgroup register file** (`occupancy_feasible`). Tensile's
`KernelWriterAssembly.functionSuffix` sets `overflowedResources = 4` when

```
vgprPerThreadPerOccupancy = 65536 // NumThreads
numWorkGroupsPerCU        = vgprPerThreadPerOccupancy // max(vgpr, agpr)
if numWorkGroupsPerCU < 1:  overflowedResources = 4     # "resulted in error 4"
```

The accumulator set is always allocated, so it is a *sound lower bound* on
`vgprPool.size()`; with `NumThreads = (MT0/TT0)*(MT1/TT1)*LSU` the accumulator
count per workgroup is exactly `weight * MT0 * MT1 * LocalSplitU`, so
**ThreadTile cancels**. The rule:

```
weight * MT0 * MT1 * LocalSplitU >= 65536   ->   refuse
```

with `>=` (not `>`): an accumulator set that exactly fills the file leaves no
VGPR for operands or addresses, so Tensile must overflow. Catches
`C 128x128x8/tt4x4` (12 phases), `Z 128x128x8/tt4x4` (6), `Z 128x64x8/tt4x4`
(14), `Z 64x128x8/4x8` (8) — **40 empty phases, 0 built refused**. It is also the
constraint the *retired* area model (`R*MTarea <= 65536/2`) was reaching for,
with the wrong threshold (32768, not 65536) and the wrong boundary (`>`, not
`>=`); §R27 is what that buys.

**(2) The LSU LDS reduction** (`occupancy_feasible`). `LocalSplitU > 1` makes
Tensile allocate a reduction buffer of `multiplier * LSU * MT0 * MT1` elements
(SolutionStructs:4108), `multiplier = ComputeBytes // LoadBytes`, so in bytes it
is exactly `LSU * MT0 * MT1 * ComputeDataType.numBytes()`; :4334 refuses past
`MaxLDS = 65536`:

```
LocalSplitU > 1 and LSU * MT0 * MT1 * ComputeBytes > 65536   ->   refuse
```

This is the `Kernel Uses 131072 > 65536 bytes of LDS` class (13 phases, 0 built
refused). R23 deferred it pending a "destination element size table"; it is the
*compute* dtype that matters (`ComputeDataType.numBytes()`, table at
`vgpr_model.COMPUTE_BYTES_PER_ELEMENT`, HPA → f32 4 B), not the destination's.

**(3) `AggressivePerfMode = 2` is non-generative** (`candidate.py`, the
*generator* seam). Tensile declares the domain `[0,1,2]` (Common.py:1446) but
`Components/Priority.py` dispatches the priority component by exact match on the
boolean fingerprints `{False}` / `{True}`, so 2 matches neither, `Priority.find`
returns `None`, and `MAC_F32C.__call__` raises `TypeError: 'NoneType' object is
not callable` before a kernel exists. Measured: **0 of 28 built**, across all
seven families. Refused at the *generator* seam, not the writer: the writer's
contract test probes APM=2 to prove the *forwarding*, so the writer keeps
forwarding any value and the *drawer* refuses the dead one — the same split as
`AssertSizeMultiple: [1]`.

R23's second deferred item — the **NumThreads-aware VGPR budget** — is rule (1),
and it resolved *differently* than R23 expected. R23 wanted a config-exact VGPR
table because the *measured-total* form cost one false rejection on a measured
kernel. It does not need one: the accumulator form carries no measured table,
which is what removes the overreach.

## R25 — the tie taxonomy on run_20261018_004835 (20 WIN / 18 TIE / 0 LOSS)

`resolve_cells` is regenerated against the latest run. The 18 ties, with the
mechanical native-vs-floor gap `cfg_gap` and the measured margin (`Δ %` = native
over floor):

| cell | `cfg_gap` | Δ % | native winner | floor winner |
|---|---|---|---|---|
| CC:512 | identical | +4.4 | `64x64x8 / 4x4 / VW2 / DU8` | same |
| DD:768 | identical | +1.5 | `64x64x8 / 4x4 / VW2 / DU8` | same |
| DD:1024 | **retile** | +1.2 | `64x32x8 / 4x2 / VW1 / DU8` | `64x64x8 / 4x4 / VW2 / DU8` |
| DD:1365 | **retile** | +2.2 | `32x32x8 / 2x2 / VW1 / DU16` | `64x64x8 / 4x4 / VW1 / DU8` |
| DD:2048 | near | +2.3 | `64x64x8 / 4x4 / **VW2** / DU8` | `64x64x8 / 4x4 / VW1 / DU8` |
| HH:1024 | identical | +1.3 | `128x128x16 / 8x8 / VW8 / DU16` | same |
| HH:2048 | identical | +3.7 | same + `PGR=0 NLCA=1 LdsPadA=0` | same |
| HH:4096 | identical | +3.3 | same + `PGR=0 NLCA=1 LdsPadA=0` | same |
| HH_HPA:1024 | no-floor | +0.1 | `64x128x16 / 4x8 / VW4 / DU16` | — |
| HH_HPA:2048 | no-floor | −0.0 | `64x128x16 / 4x8 / VW4 / DU16` | — |
| HS_HPA:1024 | no-floor | +0.1 | `128x64x16 / 8x4 / VW4 / DU16` | — |
| HS_HPA:2048 | no-floor | +3.3 | `64x128x16 / 4x8 / VW4 / DU16` | — |
| SS:768 | identical | +1.1 | `128x128x8 / 8x8 / VW4 / DU8` | same |
| SS:1000 | identical | +3.7 | same | same |
| SS:1024 | identical | +4.6 | same | same |
| SS:1365 | identical | +3.8 | same | same |
| SS:2048 | near | +1.1 | `128x128x**16** / 8x8 / VW4` | `128x128x**8** / 8x8 / VW4` |
| SS:4096 | near | +3.4 | `128x128x**16**` | `128x128x**8**` |

Readings:

* **(a) identical — 13 of 18.** The native winner *is* the floor's tile
  (`CC:512`, `DD:768`, `HH:1024/2048/4096`, `SS:768/1000/1024/1365`). This is the
  "unedited steal" reading, and it is correct: on `HH` the only difference is
  `PGR=0 NLCA=1 LdsPadA=0` — knobs that did not move the needle.
* **(b) near — 4.** The floor's tile with one `VectorWidth` or `DepthU` step
  (`DD:2048` VW 2-vs-1; `SS:2048/4096` DU 16-vs-8). The lever is a width/depth
  probe, not a tile probe.
* **(b′) retile — 2.** `DD:1024` and `DD:1365` tie on a *smaller, different* tile
  than the floor's. The lever is a **tile** probe.
* **(c) no-floor — 4.** `HH_HPA:1024/2048`, `HS_HPA:1024/2048`: the gfx900 chain
  ships no HPA kernel, so there is nothing to beat; native is at 123–129 % of the
  family ceiling. Not a deficit, not a target.

`DD:2048` native already sits at **100.2 % of the realistic DD ceiling** (floor
96.6 % of median) — DD's big shapes are closed by physics, not by a kernel gap.
The report's tie band this run is bracketed by the largest tie (`SS:1024`,
+4.6 %) and the smallest win (`CC:256`, +7.8 %).

## R26 — the straggler class tracker

The "laundry list" is four classes, not one, and each has its own lever. The
magnitudes are the `Δ %` column above.

| class | cells | the lever | best-possible margin |
|---|---|---|---|
| **C1 — same-geometry ties** | `CC:512`, `DD:768`, `HH:1024/2048/4096`, `SS:768/1000/1024/1365` | non-tile knobs on the winner geometry | ≤ +4.6 % |
| **C2 — near ties (VW/DU)** | `DD:2048`, `SS:2048`, `SS:4096` | a `VectorWidth` / `DepthU` step | ≤ +3.4 % |
| **C3 — retiles** | `DD:1024`, `DD:1365` | a tile probe (native is on a *smaller* tile) | ≤ +2.2 % |
| **C4 — no-floor HPA** | `HH_HPA:1024/2048`, `HS_HPA:1024/2048` | none — nothing to beat | ~0 |

Per class, the four route kinds:

* **wide** — *closed for the complex families* (§R27): no CC tile with area >
  8192 and no ZZ tile with area > 4096 is legal. Still open for `SS`/`HH` (area
  up to 256×256), but those cells already sit at 99–112 % of ceiling with the
  floor's own 128×128 tile, so a wider tile is an LDS-bound bet with little
  headroom.
* **narrow** — open everywhere, and *proven* by C3: at `DD:1024/1365` a
  *smaller* tile ties, and `DD:192/256/512` **win** with `32x32` (+267 %/+20 %/
  +7 %). Narrow is the lever for the 7-CU occupancy cliff.
* **steal** — **no steal is in this run, and none is justified.** There are 0
  LOSS cells; the ties are byte-identical floor tiles (i.e. already stolen); and
  the one steal that had content — `CC:256` (R8) — has already landed as a WIN.
  Stealing a gfx900 config *adds nothing* where the gfx900 config is already what
  native ships, which is every tie. The steal route stays closed until a native
  LOSS appears, and then only for that cell.
* **novel** — R18's routes A–I applied to the winner geometry: the `PLAN_BATCH`
  rows. These are the only levers left for C1/C2.

`DD` is the **only family whose winner tile changes by shape** (`32x32` at
192–512, `64x64` at 768–2048, `64x32`/`32x32` retiles at 1024/1365). That is the
signature of a tile-sensitive family; the right lever is a tile probe, and the C3
cells are exactly where it has not been run.

The **CC:256 steal port record** — the "bit-by-bit gfx900 → gfx90c adaptation"
requirement — is §R8 above: only `MacroTile 64x64`, `WorkGroup 16x16x1` and
`GLVW 2/2` were taken verbatim (all three are self-consistent consequences of
MT/TT/VW, not vendor magic numbers), and `StaggerU`, `WGM`, `LdsPad`,
`AssertFree*ElementMultiple`, `PGR` and `LSU` were all re-swept because the source
part has 60 CUs and HBM2, not 7 CU and DDR4. It is the template for a future
steal, and the reason none is run now.

## R27 — the tile axes now have provable ceilings

Three CPU-only constraints bound every tile. All three are calibrated
zero-false-rejection on the corpus, so "illegal" here means Tensile will not
build it:

1. **Workgroup register file** (§R24 rule 1): `weight * MT0 * MT1 * LSU < 65536`.
   With the per-dtype accumulator weight `R` (`S/H` 1, `D` 2, `C` 4, `Z` 8) the
   ceiling is `MT0*MT1 < 65536 / R`: `SS/HH` 65536, `DD` 32768, `CC` 16384,
   `ZZ` 8192.
2. **LDS tile budget** (`occupancy_feasible`): `(MT0+MT1) * DepthU *
   bytes(LDS row) <= 16384`.
3. **Classic-load divisibility** (`validate_tensile_loads`): `MT0*DU` and `MT1*DU`
   must divide by `NumThreads * GLVW`.

**Consequence (brute force, pinned by
`test_no_legal_complex_tile_is_wider_than_the_measured_max`):** over every CC tile
with area > 8192 and every ZZ tile with area > 4096, at every thread tile that
survives the per-thread budget, **not one is legal**. So:

| family | widest legal MacroTile | widest ever *emitted* |
|---|---|---|
| CC | `128x64x8` (or `64x128x8`) | `128x64x8`, but at VW1 — never VW2 |
| ZZ | `64x64x8` / `128x32x8` / `32x128x8` | `128x32x8`, but at tt2x8 — never tt4x4 |

This **retires §8.2** ("Tiles that are legal but were never generated"): its four
"headroom" tiles — `ZZ 128x128x8`, `ZZ 128x64x8`, `CC 128x128x8`, `CC 128x96x8` —
are all **illegal**, and the claim that they were "legal" was wrong. The old gate
read the *per-thread* budget (`TT0*TT1*R <= 128`), which those tiles pass (128
exactly), and not the *workgroup* budget, which they fill (65536). The
`128x96x8/8x4` row additionally fails divisibility
(`totalElements 1024 % (NumThreads*glvw) 768 != 0`).

The legal-wide rows now in the deck are in §R30.

## R28 — the ledger trace: what was tried, per cell

Search breadth from the registry's own generation log (`phases`) — distinct
`(MacroTile, ThreadTile, VectorWidth, DepthU)` geometries per cell — plus the
proposal ledger's outcomes for the tie cells:

| family | generation attempts | distinct geoms / cell (big shapes) |
|---|---|---|
| SS | 409 | 64–88 |
| HS_HPA | 147 | 84–85 |
| HH_HPA | 175 | 81 |
| HH | 103 | 57 |
| CC | 59 | 13–16 |
| DD | 58 | 16 |
| **ZZ** | **50** | **5** |

| tie cell | proposals | functional | rejected | slow | pending |
|---|---|---|---|---|---|
| CC:512 | 1 | 1 | 0 | 0 | 0 |
| DD:768 | 3 | 0 | 1 | 2 | 0 |
| DD:1024 | 0 | 0 | 0 | 0 | 0 |
| DD:1365 | 1 | 0 | 0 | 1 | 0 |
| DD:2048 | 0 | 0 | 0 | 0 | 0 |
| HH:1024 | 14 | 13 | 1 | 0 | 0 |
| HH:2048 | 8 | 6 | 2 | 0 | 0 |
| HH:4096 | 12 | 9 | 3 | 0 | 0 |
| HH_HPA:1024 | 40 | 28 | 5 | 3 | 4 |
| HH_HPA:2048 | 34 | 32 | 0 | 0 | 2 |
| HS_HPA:1024 | 27 | 18 | 4 | 5 | 0 |
| HS_HPA:2048 | 29 | 20 | 3 | 3 | 3 |
| SS:768 | 18 | 6 | 6 | 6 | 0 |
| SS:1000 | 24 | 14 | 6 | 4 | 0 |
| SS:1024 | 21 | 10 | 9 | 1 | 1 |
| SS:1365 | 19 | 10 | 7 | 2 | 0 |
| SS:2048 | 15 | 9 | 6 | 0 | 0 |
| SS:4096 | 13 | 8 | 4 | 1 | 0 |

What this says:

* **ZZ is under-searched by an order of magnitude** — 5 distinct geometries per
  cell against SS's 64–88 — and it is the family furthest from its ceiling
  (17–25 %). The `pending` count for ZZ is 0, so the draw queue is not the
  blocker; the **deck** is (5 rows is not a search). §R30 widens it.
* **The complex families carry the most `legal_slow`** (`DD:768` 2/3, `SS:768`
  6/18, `SS:1365` 2/19): the draws built, ran, and were slow — geometry
  saturated, not the gate.
* **The retile cells (`DD:1024/2048`) have zero proposals.** Their tie was found
  by the deck, not by the mutator; a tile probe is the untried lever (C3).
* **`HH_HPA`/`HS_HPA` have the deepest queues** (40/34/27/29 proposals) and the
  smallest margins — budget spent where there is nothing to beat.
* `phases` generation attempts per family sum to 409+58+50+59+103+175+147+19 =
  1020; the 38 pending proposals are unresolved draws the overnight run should
  now resolve (all gate-legal after §R24).

## R29 — which kernel types perform best (the pattern across all runs)

From the winners on this run (all 38 cells) and the corpus census:

* **Small cubes want a SMALL tile and many workgroups.** `SS:256` is won by
  `96x96x16 / 6x6 / VW2 / WGM8` at **+231 %** over the floor's `32x64` big tile;
  `HH:256` by `32x64x16 / 4x4 / VW4` at **+277 %**; `DD:192` by `32x32x8 / 2x2`
  at **+267 %**. The floor ships a rank-1 tile for a cube that cannot fill it.
* **Big real cubes (SS/HH ≥ 512) want the vendor rank-1 tile** —
  `128x128x8|16 / 8x8 / VW4|8`, `WGM4`. It wins at `HH:512` (+22 %) and `SS:512`
  (+10 %), and *ties* above; the only in-band gains left are `DU 16` at
  `SS:2048/4096`.
* **`DD` tracks the cube size** (`32x32` → `64x64` → retiles) and is at 94–100 %
  of ceiling once the cube is ≥ 768.
* **`CC` and `ZZ` are issue-bound, not area-bound.** Complex costs four real FMAs
  per complex MAC with no MFMA, and `ZZ` is FP64 at 1/16 rate; both run at
  17–31 % of ceiling and cannot be fixed by area (which is capped anyway, §R27).
  Their lever is **occupancy** — the smallest tiles already win (`CC 64x64/4x4`,
  `ZZ 32x32/2x2`).

The highest-yield band in the whole corpus is therefore the **small-shape band**
(`SS/HH/DD` at 192–512), where the floor is worst and the margins are +20 % to
+277 %. The big-shape band is a knob surface around a tile that is already the
vendor's.

## R30 — the deck changes for this run

* **`phases.yaml`: 4 dead rows replaced.** The `ZZ trialD3` rows
  (`mt128x128x8_tt4x4`, `mt128x64x8_tt4x4` at 512³ and 1024³) fail the workgroup
  register-file rule (`8·128·128 = 131072`, `8·128·64 = 65536`), so they can
  never generate. Replaced with the **widest legal ZZ tiles**, `128x32x8/4x4` and
  `32x128x8/4x4` (fingerprints recomputed). `check_candidates --quiet` goes
  4 illegal → **0 illegal**.
* **`decks.py`:** the CC "widest legal MacroTile" rows `128x128x8/8x4`,
  `128x128x8/4x8`, `128x96x8/8x4` are replaced with `128x64x8/8x4|4x4` and
  `64x128x8/4x8` (VW2) — the *provable* widest legal CC tile, never emitted at
  VW2. The ZZ rows `128x128x8/4x4`, `128x64x8/4x4` become `128x32x8/4x4` and
  `32x128x8/4x4`.
* **`DECISION_TRIAL_TILES` D3** becomes the widest legal ZZ pair (D1/D2
  unchanged).
* **New model pins (tests):** `TestWorkgroupRegisterFile`,
  `TestLdsReductionBuffer` (`tests/test_occupancy_gate.py`);
  `test_generator_refuses_the_dead_perf_mode` and
  `test_no_legal_complex_tile_is_wider_than_the_measured_max`
  (`tests/test_knob_sweep.py`).
* **Preflight is the authority, not a number written here.** `python3
  check_candidates.py --quiet` → `0 illegal`;
  `python3 -m oto.harness.generate_candidates --dry-run` → `0 refused`;
  `PYTHONPATH=. python3 oto/runners/cli.py --preflight` → parity (38/38 cells).

## R31 — what to stop doing

* **Chasing a wider MacroTile for C and Z** — provably closed (§R27), not a
  budget question.
* **ThreadTile width ladders for C and Z** — the accumulator cap makes every
  wider tile illegal.
* **Stealing a gfx900 config for a TIE** — the tie *is* the stolen config; the
  route has nothing to add until a LOSS appears (§R26).
* **`MatrixInstruction` / `DirectToLds` / `WavefrontSize` / `-mllvm -amdgpu-*`** —
  rejected or harmful on gfx90c.
* **Hunting HPA ties** — no floor exists and native is at 123–129 % of ceiling.
* **Re-pinning `KNOB_SWEEP_BASES`** — the sweep tests index `[0]` and the D4
  widen needs CC at VW1; winner-geometry work goes in `PLAN_BATCH`.
* **`AggressivePerfMode = 2`** — now refused at the generator seam (§R24).
* **Reading a single `best`-seed sample as a verdict** — judge within-run, ≥3
  seeds, on the median, inside the report's tie band.

## R32 — the overnight command

```bash
# CPU-only, safe under GNOME (no GPU stress):
python3 check_candidates.py --quiet
python3 -m oto.harness.generate_candidates --dry-run
python3 -m oto.harness.gate_calibration --population ours --fail-on-false-reject
python3 -m oto.harness.failure_triage
PYTHONPATH=. python3 oto/runners/cli.py --preflight
python3 -m pytest -q tests/test_occupancy_gate.py tests/test_knob_sweep.py

# TTY only — the real run:
python3 port_tensile.py --auto --budget 10 --yes
```

The gate calibration must print `0 MISS` and `0 FALSE REJECTION`; if it does not,
a new phase is a gate bug, not a kernel result.

---

## Superseded: rewrite 5 (2026-10-17), kept below for history

Supersedes rewrite 4 (R10–R15, kept below for history). **What is new here** is
the straggler trace on the latest A/B, a per-cell **tie taxonomy** that separates
genuine work from measurement noise, the **launch-boundary forwarding surface**
that decides which of R15's "virgin axes" are real, the **adaptation routes**
(R18) that break the big-shape ties *without* stealing, and the deck rows that
carry them (R19).

**Owns:** the candidate deck, the routes, the search rules. Does not own:
ceilings and verdict bars (`gfx90c_theoretical_limits.md` §5), measured evidence
(`results.md`), hardware facts (`gfx90c_theoretical_limits.md` §1–§3),
or the per-cell winners (`gfx90c_results/analysis/cells_resolved.full.txt`).

---

## R16 — the forwarding surface: which knobs actually reach Tensile

One fact, one home: `oto/tensile/config_writer.py` is the **only** place a knob
becomes Tensile YAML, and it now *declares* that surface as data —
`FORWARDED_KNOBS` (what reaches Tensile) and `NOT_FORWARDED_KNOBS` (valid
parameters it does not reach), pinned to the fork helpers by
`tests/test_writer_forwards_sweep_knobs.py`. The helpers behind them are
`_fork_thread_macro_workgroup`, `_fork_split_knobs`, `_fork_depth_u`,
`_fork_width_knobs`, `_fork_coalesced_loads`, `_fork_prefetch` and
`_fork_sweep_int_knobs`, plus the `FORWARDED_GROUP_C_KNOBS` tuple. A key outside
`FORWARDED_KNOBS` is silently dropped at the launch boundary and the candidate
then benchmarks at the Tensile default — a no-op that reads in the ledger as a
measured negative. This is the failure mode the module docstring calls out ("the
one place that has to answer for every silent-drop bug").

| group | knobs forwarded |
|---|---|
| tile | `MacroTile`, `ThreadTile`, `WorkGroup` (with `LocalSplitU` as element [2]), `DepthU` |
| width | `VectorWidth`, `GlobalLoadVectorWidthA/B` |
| split | `GlobalSplitU`, `WorkGroupMapping` |
| loads | `NumLoadsCoalescedA/B` (and the `NLCA` alias) |
| prefetch | `PrefetchGlobalRead` (int 0/1/2), `PrefetchLocalRead` (bool) |
| sweep ints | `UseSgprForGRO`, `InnerUnroll`, `MaxOccupancy`, `AggressivePerfMode`, `FractionalLoad`, `NonTemporalA/B`, `AssertFree1ElementMultiple` |
| Group C | `LdsPadA/B`, `AssertFree0ElementMultiple`, `StaggerU`/`StaggerUMapping`/`StaggerUStride`, `StoreCInUnroll` |

`GlobalReduceVectorWidth` is a trap in the *other* direction: `_fork_width_knobs`
emits it (reference metadata spells it `grvw`) and `_drop_unsupported` then strips
it, because it is not a Tensile parameter at all. It is in neither tuple.

**Not forwarded (`NOT_FORWARDED_KNOBS`) — dead letters until the launch boundary
is extended (R20):** `WaveSeparateGlobalReadA/B`, `ThreadSeparateGlobalReadA/B`,
`1LDSBuffer`, `TransposeLDS`, `UnrollMajorLDSA/B`, `GlobalReadPerMfma`,
`LocalWritePerMfma`, `DepthULdsDivisor`, `PersistentKernel`,
`LdsBlockSizePerPadA/B`, `DirectToVgprA/B`. The harness strips these at emit time
and *reports* the strip (`candidate_rows._NOT_FORWARDED_YET` is that tuple), so a
candidate carrying one is now a reported no-op rather than a silent one.

This corrects R15: its items 8 (`WaveSeparateGlobalRead`) and 9 (`1LDSBuffer`)
were listed as deck additions, but the writer does not forward either, so a
candidate carrying them would have benchmarked at the default, and the overnight
budget would have been spent on a placebo. Of R15's route-B table, only the
rows whose knob appears in the table above are executable.

## R17 — the tie taxonomy (latest A/B: 19 WIN / 19 TIE / 0 LOSS, 0 RED / 12 ORANGE)

The 19 ties are not one problem. `resolve_cells` reports the mechanical gap
between the native winner's config and the floor's as `cfg_gap` and the classes
it produces are the taxonomy below — so this split is now checkable, not read:

**(a) Same-geometry ties (`cfg_gap=identical`)** — native's winning tile is the
floor's, and at most a couple of non-tile knobs differ (and did not move the
needle): the tile is
byte-for-byte identical at `CC:256`, `CC:512`, `DD:768`, `HH:1024`, `SS:1000`,
`SS:1024`, `SS:1365`, and identical-but-for-`NLCA`/`PGR`/pad at `HH:2048`,
`HH:4096`, `SS:768`. This is the user's reading, confirmed against
`cells_resolved.full.txt`: the two complex/medium cells reproduce
`MT=[64,64] TT=[4,4] VW=2 DU=8` and the four wide cells reproduce
`MT=[128,128] TT=[8,8] VW∈{4,8} DU∈{8,16}`.

**(b) Near ties (`cfg_gap=near`)** — native's winner keeps the floor's tile and
differs only in a `VectorWidth` or `DepthU` step: `DD:2048` (VW 2 vs 1),
`SS:2048` and `SS:4096` (DU 16 vs 8).

**(b′) Re-tiles (`cfg_gap=retile`)** — native ties on a *different* tile than the
floor's, and a smaller one: `DD:1024` (`MT=[64,32] TT=[4,2] VW=1` against the
floor's `MT=[64,64] TT=[4,4] VW=2`) and `DD:1365` (`MT=[32,32] TT=[2,2] DU=16`
against `MT=[64,64] TT=[4,4] DU=8`). These were folded into (b) on the first
reading and that was wrong — the deficit they carry is a tile choice, not a
width step, so the lever is a *tile* probe, not a VW/DU probe.

**(c) HPA ties (`cfg_gap=no-floor`)** — `HH_HPA:1024/2048`, `HS_HPA:1024/2048`.
These carry **no floor at all** (the gfx900 chain ships no HPA kernels), so a
"tie" here is a comparison against the undone reference arm; native already sits
at 123–129 % of the family ceiling. Not a kernel deficit — do not over-invest.

**Why same-geometry ties exist.** gfx900 (56–60 CU, 2 MiB L2, HBM2) and gfx90c
(7 CU, 1 MiB L2, DDR4 UMA) differ *only* in CU count, L2 size and bandwidth.
The data-path shape — wave64, 64 KiB LDS/CU, the same VGPR file, no MFMA — is
identical, so the vendor's rank-1 tiles transfer unchanged. At k ≥ 768 the L2
difference stops biting (a 128×128 tile holds 16 KiB of LDS, not L2), which is
exactly where the ties live.

**Why nothing has beaten them.** The knob-sweep deck perturbs
`KNOB_SWEEP_BASES`, and both relevant bases are the *wrong* tile: CC's base is
`VectorWidth 1` while CC's winner is VW2 (the D4 paired-widen row pinned it to
VW1 deliberately), and HH's base is VW4 while HH's winner is VW8. So the twelve
sweep rows never once perturbed the geometry that ties. R19 fixes that where the
tile is explicit (PLAN_BATCH), not by re-pinning the sweep bases — the sweep
tests index `KNOB_SWEEP_BASES[family][0]` and the D4 row depends on CC staying
VW1.

**What the ties are not.** No tie is a RED cell and none is a LOSS. The twelve
ORANGE cells (< 50 % of the family ceiling) are yardstick artefacts: complex
pays four real FMAs per complex-MAC with no MFMA opcode, and 128³/256³ cubes
cannot fill 7 CUs — native is 1.1–3.8× the floor on all twelve. The one cell that
was a genuine shortcoming (CC:256, the only ever-LOSS) now reads TIE at +4.2 %.

## R18 — the executable adaptation routes (all knobs forwarded per R16)

These are the levers R17's analysis leaves standing. Each is a *single-knob or
small compound change on the measured winner geometry* — except for the two
re-tile cells (R17(b′): `DD:1024`/`DD:1365`), whose lever is a **tile** probe,
not a width probe.

| # | route | knobs | cells | mechanism |
|---|---|---|---|---|
| A | **L2 pollution** | `NonTemporalA/B ∈ {1}` | SS/HH big, DD 768+ | stream past the 1 MiB shared L2 instead of thrashing it; the floor ships 0 everywhere |
| B | **Residency clamp** | `MaxOccupancy ∈ {8,12}` | all ties | pads per-workgroup LDS to `DeviceLDS // N`; 7 CUs makes wave count scarcer than on the 60-CU parts AMD tuned for |
| C | **LDS-cap branch** | `AggressivePerfMode = 2` | all ties | described as a 2-waves/SIMD LDS cap; the corpus median is already 2 waves/SIMD, so it is either free or a real clamp |
| D | **Issue-slot reduction** | `InnerUnroll = 2`, `NumLoadsCoalescedA/B`, `UseSgprForGRO` | CC, ZZ, and the wide tiles | complex and ZZ are issue-bound; longer unroll and coalesced loads cut loop-control issues, `UseSgprForGRO` moves GRO offsets from VGPR to SGPR |
| E | **Wave-fill** | `LocalSplitU = 2`; `GlobalSplitU ∈ {2,4}` | LSU: all; GSU: **SS/DD only** | the 7-CU cliff. GSU is gate-refused for every half and complex family, so LSU (which splits the M extent inside one workgroup, no reduction kernel) is the legal equivalent there |
| F | **Bank conflicts** | `LdsPadA/B ∈ {1,2,4}` | CC, ZZ, DD, SS, HH, HPA | GCN LDS is 32 banks × 4 B, `bank = (addr/4) mod 32`, wave64 serviced in 8 phases of 8 lanes. **DD, CC and ZZ are never padded in the floor** — a blind spot shared by Tensile's own `Perf/*.yaml` — so this is the highest-yield untested axis for the complex families |
| G | **Swizzle** | `StaggerU ∈ {0,8,16}` + `StaggerUMapping ∈ {0,1,2}` + `StaggerUStride ∈ {0,128}` | all ties | `StaggerU = 32` was a 56-CU raster choice, pinned corpus-wide; `StaggerUStride = 256` silently rounds to `DepthU × bpe`, so the live stride values are 0/64/128 |
| H | **Prefetch depth** | `PrefetchGlobalRead ∈ {0,2}`, `PrefetchLocalRead ∈ {0}` | CC, ZZ, SS, HH | the floor never emits PGR 2; PGR 0 / PLR 0 halve register and LDS double-buffer pressure on the VGPR-bound complex tiles |
| I | **Negative WGM family** | `WorkGroupMapping ∈ {-1,-4}`, also `{1,2,3,8}` | all ties | WGM 8 asks for eight J-column workgroups before wrapping on a 7-CU part; the negative (I/J-swap) family has never been generated at all |

`MatrixInstruction`, `DirectToLds*`, `WavefrontSize` and the `-mllvm -amdgpu-*`
flags remain out of scope: on gfx90c they are `SolutionStructs`-rejected outright
or actively harmful (`DirectToLds` blocks `NLCA > 1`, forces `GLVW = 1` on 8/16-B
dtypes, and forces `1LDSBuffer`).

## R19 — the deck changes for this overnight run

* **PLAN_BATCH: +37 tie-adapt rows (36 net-new after fingerprint dedup).** R18 A–I applied to the *measured winner
  geometry* of each tie cell — SS `128x128x8/8x8/VW4/DU8` and
  `128x128x16/8x8/VW4/DU16`; HH `128x128x16/8x8/VW8/DU16`; DD `64x64x8/4x4/VW2/DU8`
  (the DD:768/2048 winner — DD:1024/1365 tie on *different, smaller* tiles per
  R17(b′), so those two get a tile probe next, not a width probe); and the
  HH_HPA / HS_HPA winners. Every row uses only forwarded knobs (R16), so
  none is a placebo; `iter_candidates` gate-verifies each against
  `validate_config` + `ldspad_feasible`, and a refusal is reported, never dropped
  silently. This is the same template the CC:256 steal batch uses, applied to the
  cells that actually tie.
* **`knob_sweep.py` repaired.** The module referenced `KNOB_SWEEPS` /
  `KNOB_SWEEP_BASES` at module scope without importing them, so its CLI raised
  `NameError` and three tests were red. Now imported; the sweep test file is green.
* **Preflight is the authority, not a number written here** (`claude.md`: never
  write a corpus count down). `python3 -m oto.harness.generate_candidates --dry-run`
  must report `0 refused`, `python3 check_candidates.py --quiet` must report
  `0 illegal`, and `PYTHONPATH=. python3 oto/runners/cli.py --preflight` must show
  full parity (38/38 shipped cells) before the run.

## R20 — the launch-boundary extension (ranked, deliberately NOT done here)

The three axes R15 wanted are real levers, but each is a `config_writer` change
plus a gate change, so they are a work item, not a deck row:

1. **`1LDSBuffer = 1`** — halves per-workgroup LDS, which doubles the resident
   workgroups that LDS capacity currently caps. Highest expected payoff because
   LDS *capacity* (not VGPR) is the binding constraint for the majority of
   kernels.
2. **`WaveSeparateGlobalReadA/B` (+ `ThreadSeparateGlobalReadA/B`)** — splits the
   LDS write by wave/thread, attacking cross-wave bank collisions on the wide tiles.
3. **`TransposeLDS` / `UnrollMajorLDSA/B`** — aligns the LDS layout with the VALU
   read order.

Each needs a one-line addition to `_fork_params` **and** the occupancy gate taught
the changed footprint, or the gate mis-predicts feasibility. Until then they stay
out of the deck: a candidate carrying them is a no-op (R16).

## R21 — what to stop doing

* **ThreadTile width ladders for C and Z** — the accumulator cap makes every
  wider tile illegal; pure rejects.
* **`MatrixInstruction` / `DirectToLds`** — rejected or harmful (R18).
* **Hunting HPA ties** — no floor exists to beat and native is already at 123–129 %
  of the ceiling (R17c).
* **Re-pinning `KNOB_SWEEP_BASES`** to chase a winner — the sweep tests index
  `[0]` and the D4 widen depends on CC VW1; put winner-geometry work in
  PLAN_BATCH instead (R17, R19).
* **Reading a single `best`-seed sample as a verdict** — judge within-run, ≥3
  seeds, on the median, ±2 % tie band.

## R22 — the overnight command

```bash
# CPU-only, safe under GNOME (no GPU stress):
python3 check_candidates.py --quiet
python3 -m oto.harness.generate_candidates --dry-run
PYTHONPATH=. python3 oto/runners/cli.py --preflight

# TTY only — the real run:
python3 port_tensile.py --auto --budget 10 --yes
```

The overlay `gfx90c_results/overlays/phases.seed.overlay.yaml` is a generated,
gitignored artifact; it has already been refreshed for this run with
`python3 -m oto.harness.generate_candidates` (no `--dry-run`), which appended the
tie-adapt rows.

Sizing is honest-estimate territory: the latest completed run took 8 h 39 m wall
clock, and the tie-adapt rows add ~36 phases on top of the existing deck, so plan
for a full overnight window. The full desktop (GNOME) session must not launch
this: ring timeouts and GPU resets under a loaded compositor are a known failure
mode — the run belongs in the user's TTY.

---

## R23 — the failed-candidate triage, and the two gates that now refuse them

Every failed candidate from every run was re-read CPU-only from three sources:
the ledger (`registry.db` `proposals`), every run directory's empty phases, and
the two latest live runs in full. The classes, worst first, with what happened to
each:

| class | evidence | disposition |
|---|---|---|
| **ZZ `VectorWidth=2` cleared the 16 B cap** | live `phase_cand_zz_..._vw2` refused by Tensile with `GlobalLoadVectorWidthA * DataType.numBytes() > 16`, 0 CSV; every other ZZ phase at VW1 built | **fixed.** The load gate's `Z` row held ComplexFloat's numbers (2 registers, 8 bytes) for complexDouble. It now reads 4/16 (Tensile `DataType`, ComplexDouble), and `tests/test_measurement_integrity.py` pins the whole row to Tensile so the load gate and `FAMILY_BYTES_PER_ELEMENT` cannot split again. It also fixes the derived default: with `reg=4`, an absent `VectorWidth` derives 1, matching the phases that built. |
| **`LocalSplitU=2` was never in the thread count** | 24 live phases: the 4 that built (CC `64x64x8/4x4`, HH `128x128x16/8x8`) vs 20 dead on `GlobalLoadVectorWidthA 2 % pv 4 != 0` (ZZ/DD `32x32x8/2x2`) and `Kernel Uses 131072 > 65536 bytes of LDS` (SS/HH_HPA `128x128x8/8x8`) | **fixed.** Tensile computes `NumThreads = SubGroup0 * SubGroup1 * LocalSplitU` (SolutionStructs:1964) and reads LSU from `WorkGroup[2]`; the gate read the tile alone, so the sweep looked legal. The gate now reads what Tensile will receive (see the shadowing row below). The sweep's family list is narrowed to the two that survive. |
| **`AggressivePerfMode=2` builds nothing** | every family and every tile, two runs: 0 `.hsaco`, 0 CSV, while the mode-1 control in the same run built 20 (one per target arch). Tensile writes the source, then fails to compile it | **removed** from the sweep, with the evidence recorded in `decks.py`. Not a gate: no tile property predicts it, so it is a deck decision like the retired `BufferLoad` row. |
| **GLVW coupling; NLCA/LDS/StaggerU coupling** | ~21–25 % of mutator draws were illegal before the fix | **already fixed** by R18's joint domains. |
| **A knob shadowed by an explicit `WorkGroup`** | the deck's two `CC` steal rows carried `WorkGroup: [16,16,1]` *and* `LocalSplitU: 2`, so they benchmarked at LSU 1 while their note claimed LSU 2 | **fixed on both sides.** `config_writer._fork_tile` emits an explicit `WorkGroup` verbatim and only folds `LocalSplitU` in when WorkGroup is absent — so `LocalSplitU` (declared honoured in R16) is a silent no-op beside one. The gate now reads the *emitted* value (a `WorkGroup` third element wins), and the two rows no longer pass an explicit WorkGroup, so their LSU lands. |
| **`Invalid parameter name: GlobalReduceVectorWidth`**, missing `configs/phase_*.yaml`, `resource_tracker` `ValueError` | historical only — the Sep-28 reference replays, the reference-resume path, and Python 3.14 joblib noise | already closed (`_drop_unsupported`, the resume path) or environmental; no action. |

Two Tensile rules were **measured and deliberately left un-gated**, because each
needs a new fact and neither refuses anything the fixes above do not already
refuse on this corpus:

1. The **LSU LDS reduction** — `ldsNumElementsReduction = LSU * MT0 * MT1`
   (SolutionStructs:4108), which is what makes the `131072 > 65536` rejects. It
   needs the *destination* element size per family, which is a new table.
2. The **NumThreads-aware VGPR budget** — `65536 // NumThreads` rather than the
   fixed 128 (which is only `65536 // 512`). Calibrating it against the corpus
   cost one false rejection on a measured kernel, and the last retired VGPR model
   died of exactly that overreach; it needs a config-exact VGPR table first.

Deck hygiene that follows from the two fixes: 24 dead rows left `phases.yaml`
(the `swAggressivePerfMode2` set and the now-refused `swLocalSplitU2` tiles), 9
left the seed overlay (the ZZ VW2 candidate, two `AggressivePerfMode=2`
candidates, and six `LocalSplitU=2` ones), and 8 left the `PLAN_BATCH`
hypotheses (the same two classes). Coverage parity is unchanged (38/38 cells)
because every removed row had a surviving sibling on the same tile and shape, and
`generate_candidates` now emits a fully gate-legal set with nothing refused.

The durable Tensile mechanics behind these fixes (NumThreads/LSU, the
shadowed-WorkGroup rule, the LSU LDS reduction, the 16-B cap check order, the
APM death) live in `kernel_tuning_research.md` §4; §R23 keeps the triage
narrative and the disposition table.

---

## Superseded: rewrite 4 (2026-10-16), kept below for history

**What was new in rewrite 4** was a fresh A/B audit, a per-cell floor-vs-native
gap analysis, a kernel-type pattern read across `kernel_db.json`, and the
resulting route updates. Its numbers are superseded above; its mechanisms
(Routes A–F, the legality matrix, the open decisions) are still cited by §-number
from code comments, so they are retained verbatim below.

---

## R10 — latest A/B audit (2026-10-16, all runs folded)

30 cells total: **7 TIE / 23 UNGRADED** (no spoof floor data) / 0 WIN / 0 LOSS
on the `winner` basis. The 7 TIE cells, with the genuine gaps called out:

| cell | native | spoof | delta | verdict | cause |
|---|---|---|---|---|---|
| CC:192 | 118.2 | 43.2 | +173.2% | WIN | — |
| CC:256 | 210.8 | 214.0 | **−1.5%** | **TIE** | **the only genuine shortcoming** |
| CC:512 | 318.0 | 317.8 | +0.0% | TIE | at bar |
| CC:1024 | 344.0 | 301.4 | +14.1% | WIN | — |
| CC:2048 | 346.7 | 294.6 | +17.7% | WIN | — |
| DD:192 | 77.8 | 21.4 | +264.5% | WIN | — |
| DD:256 | 85.7 | 71.2 | +20.4% | WIN | — |
| DD:512 | 95.7 | 89.1 | +7.4% | WIN | — |
| DD:768 | 93.0 | 91.8 | +1.3% | TIE | at bar |
| DD:1024 | 92.9 | 91.4 | +1.5% | TIE | at bar |
| DD:1365 | 89.1 | 86.8 | +2.7% | TIE | at bar |
| DD:2048 | 98.6 | 96.8 | +1.8% | TIE | at bar |
| HH:256 | 763.4 | 201.5 | +278.9% | WIN | — |
| HH:512 | 1682.8 | 1388.7 | +21.2% | WIN | — |
| HH:1024 | 2581.9 | 2546.7 | +1.4% | TIE | at bar |
| HH:2048 | 2670.9 | 2658.0 | +0.5% | TIE | at bar |
| HH:4096 | 2749.3 | 2668.5 | +3.0% | TIE | at bar |
| SS:256 | 412.1 | 124.1 | +232.0% | WIN | — |
| SS:512 | 854.4 | 801.5 | +6.6% | WIN | — |
| SS:768 | 1105.4 | 1094.9 | +1.0% | TIE | at bar |
| SS:1000 | 1107.4 | 1075.2 | +3.0% | TIE | at bar |
| SS:1024 | 1135.1 | 1099.6 | +3.2% | TIE | at bar |
| SS:1365 | 1110.0 | 1073.0 | +3.4% | TIE | at bar |
| SS:2048 | 1164.0 | 1120.7 | +3.9% | TIE | at bar |
| SS:4096 | 1187.2 | 1109.8 | +7.0% | WIN | — |
| ZZ:128 | 16.8 | 4.9 | +242.9% | WIN | — |
| ZZ:192 | 20.8 | 14.8 | +40.8% | WIN | — |
| ZZ:256 | 22.2 | 17.5 | +27.0% | WIN | — |
| ZZ:512 | 23.9 | 20.6 | +16.4% | WIN | — |
| ZZ:1024 | 24.4 | 22.6 | +7.9% | WIN | — |

**The floor has no HPA families** (HH_HPA, HS_HPA) — those 8 cells are
UNGRADED because the spoof chain has no HPA kernels to compare against.
HH_HPA:512 reads 1447.0 native (no floor), HS_HPA:512 reads 1441.2 (no floor).

### Per-cell floor gap analysis (the TIE cells)

For each TIE cell, what the floor uses vs what native uses:

| cell | floor best config | native best config | gap |
|---|---|---|---|
| CC:256 | MT=[64,64] TT=[4,4] VW=2 DU=8 (214.0) | same config (210.8) | floor has MT=[128,128] (6 kernels) that native never generated; floor has TT=[8,8] (9 kernels) that native never generated |
| CC:512 | MT=[64,64] TT=[4,4] VW=2 DU=8 (317.8) | same config (318.0) | same gap: floor has MT=[128,128] + TT=[8,8] unexplored by native |
| DD:768–2048 | MT=[64,64] TT=[4,4] VW=2 DU=8 | same or MT=[64,32] TT=[4,2] VW=1 | same config class; native slightly ahead on all |
| HH:1024–4096 | MT=[128,128] TT=[8,8] VW=8 DU=16 | same config | native slightly ahead on all |
| SS:768–2048 | MT=[128,128] TT=[8,8] VW=4 DU=8 | same config or DU=16 | native slightly ahead on all |

**Key finding: the floor's CC advantage at 256/512 comes from MT=[128,128] tiles
(6 kernels, all at TT=[8,8]) that native never generated.** The floor's dominant
CC config (MT=[64,64] TT=[4,4] VW=2 DU=8) is identical to native's, and native
matches or beats it on every cell except CC:256 where the floor's 128×128 tiles
push it ahead.

### R11 — kernel-type patterns across all 25,671 kernels

From `kernel_db.json` (25,671 kernels, 11 runs):

| family | best tile | TT | VW | DU | best GF/s | pattern |
|---|---|---|---|---|---|---|
| HH | 128x128x16 | 8x8 | 8 | 16 | 2749.3 | large square, max TT area |
| SS | 128x128x8 | 8x8 | 4 | 16 | 1187.2 | large square, max TT area |
| DD | 64x64x8 | 4x4 | 2 | 8 | 98.6 | medium square, 4x4 TT |
| CC | 64x64x8 | 4x4 | 2 | 8 | 346.7 | medium square, 4x4 TT |
| ZZ | 32x32x8 | 2x2 | 1 | 8 | 24.4 | small square, 2x2 TT |

**The winning rule: ThreadTile area scales inversely with bytes-per-element.**
- 2 B (HH) → 8×8 = 64 accumulator VGPRs
- 4 B (SS) → 8×8 = 64 accumulator VGPRs (but 111 VGPR total, LDS-bound)
- 8 B (DD/CC) → 4×4 = 16 accumulator VGPRs
- 16 B (ZZ) → 2×2 = 4 accumulator VGPRs

Every family's winner sits at the largest TT satisfying `TT_area × bpe ≤ ~64`
accumulator VGPRs. This is the register-file budget, and it's why CC and ZZ are
stuck: their rule-implied TT (4×4 and 2×2) is already the winner, and the next
step up breaks the register file.

**Second pattern: LDS at the winner is always 16–25 KB, never 64 KB.** The
winners operate at 1/4 to 1/3 of the 64 KB LDS budget (2–4 resident workgroups).
That is the architectural sweet spot for this part.

**Third pattern: WorkGroupMapping is 4 or 8 at every winner, never 1.** WGM≥4
keeps neighbouring CUs on the same matrix B slice, which matters because L2 is
1 MiB shared. No winner uses WGM 2 or 16.

**Fourth pattern: the floor never pads CC/DD/ZZ.** The floor pads SS (110 LPA=2,
162 LPB=2 kernels) and HH (17 kernels) but **never pads DD, CC, or ZZ in a
single one of 2285 kernels**. Tensile's own `Perf/*.yaml` recipes likewise never
enumerate `LdsPadA/B`. That is a self-consistent blind spot in both the vendor
library and Tensile's recipes — the highest-yield untested axis.

**Fifth pattern: the floor never uses FractionalLoad=2, PGR=2,
WaveSeparateGlobalRead, or any of the other 11 "virgin" knobs.** All 2285 floor
kernels sit at the default for these. The vendor floor is aggressive on tile
geometry and conservative on everything else.

---

## R12 — gfx90c hardware read (confirmed from existing docs)

From `gfx90c_tuning_guide.md` §1.1 (primary-source legal domains),
and `gfx90c_theoretical_limits.md` §1:

| property | value | consequence |
|---|---|---|
| CUs | **7** | grid quantization cliff at small N |
| SIMDs/CU | 4 | 28 SIMDs total |
| Wavefront | 64 | 8 phases of 8 lanes per LDS access |
| FP32 lanes | 448 | 1613 GFLOPS peak (SS/DD/CC/ZZ) |
| Clock | 1800 MHz | 3226 GFLOPS packed-f16 peak (HH) |
| LDS | **64 KiB/CU** | 2 WG/CU budget at 32 KiB/WG |
| L1 | 16 KiB/CU | — |
| L2 | **1 MiB** shared | 16× smaller than gfx900's |
| DRAM | DDR4 UMA ~42 GB/s | machine balance 38 F/B at SS peak |
| MFMA | **absent** | MatrixInstruction rejected outright |
| WMMA | absent | — |
| 16 B load cap | verified | GLVW × bpe ≤ 16 |
| Max VGPR | 256/thread | accumulator budget is the binding constraint |
| Max LDS | 65536 B | LDS capacity binds 61.7% of kernels |

**The 7-CU occupancy cliff** (from `gfx90c_tuning_guide.md` §1.2 and
`gfx90c_tuning_guide.md` §1.2 (7-CU geometry)):

At 256³, a 128×128 macro tile yields 4 workgroups for 7 CUs — **6 of 7 CUs idle**.
No knob tuning recovers that; the only levers are a smaller MacroTile, more
GlobalSplitU, or LocalSplitU. At 512³, 128×128 yields 16 tiles (2.3/CU); at
1024³, 64 tiles (9/CU) — the cliff vanishes by N≥1024.

---

## R13 — route updates for the overnight run

### Route A (updated) — Spoof-steal for CC:256 only

The user's caveat is honoured: **only CC:256**, the single genuine shortcoming
(TIE −1.5%), and only because the floor already won the geometry there. The floor's
CC advantage comes from MT=[128,128] tiles that native never generated.

**Stolen-from-gfx900** (floor CC:256 winner):

| knob | floor winner | native winner today |
|---|---|---|
| MacroTile | **64 × 64** (dominant) + **128 × 128** (6 kernels) | 32 × 32 (dominant) |
| ThreadTile | 4 × 4 (55 kernels) + **8 × 8** (9 kernels) | 4 × 4 (965 kernels) |
| VectorWidth | 2 | 2 |
| WorkGroup | 16 × 16 × 1 | 8 × 8 × 1 |
| GlobalSplitU | 1 | 1 |
| DepthU | 8 | 8 |
| LdsPadA/B | 0 | 0 |
| measured | **214.0** | **210.8** (−1.5%) |

**The gfx900 → gfx90c port record** — what changes and why:

| knob | gfx900 value | gfx90c adaptation | why |
|---|---|---|---|
| MacroTile | 64×64 + 128×128 | **keep 64×64, add 128×128** | 128×128 is legal for CC at TT8x8 (128 accumulator VGPRs, within the 128 budget); the floor uses it and native never generated it |
| ThreadTile | 4×4 + 8×8 | **add 8×8** | 8×8 at 128×128 gives MT/TT self-consistency; accumulator VGPRs = 64, within budget |
| VectorWidth | 2 | **keep** | 2 × 8 B = 16 B, exactly on the verified cap |
| WorkGroup | 16×16×1 | **keep** | self-consistent with MT/TT |
| DepthU | 8 | **probe 8/16** | 16 needs 2× LDS; 8 is the safe choice on a 64 KiB/CU part |
| LdsPadA/B | 0 | **probe {1,2,4}** | CC never pads in the floor; GCN bank math says the row stride collides at power-of-2 tiles |
| StaggerU | 32 | **re-sweep 0/8/16** | 32 was chosen for a 56-CU raster |
| WorkGroupMapping | 4 | **probe {4, 8, −4}** | negative family untested; 8 is a 56-CU artefact but the floor uses it |

### Route B (updated) — The ten never-varied knobs

From the floor census (§R4):

| knob | floor value (2285/2285) | legal on gfx90c | why it could win |
|---|---|---|---|
| `LdsBlockSizePerPadA/B` | 0 | yes | per-block padding without redesigning the tile |
| `FractionalLoad=2` | 0 | yes | frees DepthU choice on ragged M/N/K |
| `PrefetchGlobalRead=2` | 0 | SS/HH only (bpe≥8 blocked) | deeper prefetch pipeline |
| `WaveSeparateGlobalReadA/B` | 0 | yes | LDS split by wave → fewer cross-wave bank collisions |
| `ThreadSeparateGlobalReadA/B` | 0 | yes | TSGR=2 works with WSGR |
| `TransposeLDS=1` | 0 | TLU=0 only | aligns LDS layout with VALU reads |
| `UnrollMajorLDSA/B=1` | 0 | yes | removes VgprForLocalReadPacking pressure |
| `1LDSBuffer=1` | 0 | SIA 2/3 only | halves LDS → doubles occupancy |
| `NonTemporalA/B = 1,2,3` | 0 | yes (glc/slc bits) | L2 pollution control on 1 MiB L2 |
| `GlobalReadPerMfma` | 1 | yes | schedules global reads between MFMAs |
| `LocalWritePerMfma` | −1 | yes | same for LDS writes |
| `PersistentKernel` | 0 | yes | amortises tile assignment on small grid |
| `MaxOccupancy < 40` | 40 | yes | artificially cap LDS to raise occupancy |
| `DepthULdsDivisor` | 1 | SIA=3 + TransposeLDS | cuts LDS usage by 2×/4× |

### Route C (updated) — Wave-quantisation ladder (SS/DD only)

From `gfx90c_tuning_guide.md` §1.2 and the 7-CU cliff analysis:

| problem | MT | G (tiles) | G mod 7 | utilisation |
|---|---|---|---|---|
| 128³ | 16×16 | 64 | 1 | 91.4% |
| 128³ | 32×32 | 16 | 2 | 76.2% |
| 128³ | 64×64 | 4 | 4 | 57.1% |
| 256³ | 32×32 | 64 | 1 | 91.4% |
| 256³ | 64×64 | 16 | 2 | 76.2% |
| 256³ | 128×128 | 4 | 4 | 57.1% |
| 512³ | 64×64 | 64 | 1 | 91.4% |
| 512³ | 128×128 | 16 | 2 | 76.2% |
| 1024³ | 64×64 | 256 | 4 | 98.8% |
| 1024³ | 128×128 | 64 | 1 | 91.4% |

Route C is legal **only for SS and DD** (GlobalSplitU > 1 is gate-refused for
all half and complex families). For CC/ZZ/HH/HPA the equivalent fix is
LocalSplitU, or nothing.

### Route D — LDS-capacity ladder for Z

Z is the only family where the winner already uses ~25 KB LDS and still binds
LDS. Drop DepthU 16→8 and 8→4 to free capacity for a second resident workgroup.

### Route E — Split-complex (3 real GEMMs)

Carried forward. Reported split GFLOPS = (4/3)·R_real for CC ≈ 1513; for ZZ
≈ 127–131. This is the only route that can *beat* the 1613/101 BLAS ceiling
rather than approach it. Needs a harness change — separate work item, not a
deck entry. **Unmeasured — treat as hypothesis.**

### Route F — Persistent-kernel / fixed-grid

gfx90c has 7 CUs. A fixed 7-workgroup grid eliminates tail-wave idle by
construction. Tensile cannot express this — conceptual route for the
kernel-writer, not a deck entry.

---

## R14 — what to stop doing

Ceasing (per floor census):
- **ThreadTile width ladders for C and Z** — the accumulator cap makes every
  wider tile illegal; pure rejects.
- **LdsPad/LDS-layout work** for families where bandwidth is oversupplied — LDS
  *capacity* is better spent on residency.
- **MatrixInstruction / DirectToLds** — rejected outright or actively harmful
  (blocks NLCA>1, forces GLVW=1 on 8/16-byte dtypes).
- **MaxOccupancy/AggressivePerfMode assumptions** without measurement — never
  swept.

Now *starting*: MacroTile ladders for C and Z at the **existing** accumulator
width — the opposite direction to a ThreadTile ladder and the one the physics
asks for.

---

## R15 — the concrete deck for the overnight run

The existing deck (rewrite 3 §8) already contains:
- `KNOB_SWEEPS`: the sweep rows covering UseSgprForGRO, GLVW (CC paired),
  InnerUnroll, PGR, NLCA, MaxOccupancy, GSU (SS/DD), LSU, StaggerU,
  FractionalLoad, NonTemporal (APM was dropped — §R23)
- `FAMILY_DECKS`: 67 tile entries across 7 families
- `DECISION_TRIAL_TILES`: 4 trial entries (D1–D3)
- CC:256 steal batch: 14 rows in `PLAN_BATCH`

The overnight run adds:
1. **CC:128×128 tiles at TT8×8** — the floor's unexplored corner (Route A)
2. **CC:LdsPad {1,2,4}** — the never-padded family (Route B)
3. **ZZ:LdsPad {1,2,4}** — the never-padded family (Route B)
4. **DD:LdsPad {1,2,4}** — the never-padded family (Route B)
5. **SS:GSU {2,4} at small shapes** — wave quantisation (Route C)
6. **DD:GSU {2,4} at small shapes** — wave quantisation (Route C)
7. **FractionalLoad=2** — the never-emitted value (Route B)
8. **WaveSeparateGlobalRead {0,1}** — the virgin axis (Route B)
9. **1LDSBuffer {0,1}** — the virgin axis (Route B)
10. **NonTemporalA/B {1,2,3}** — the virgin axis (Route B)

All entries pass `validate_config` (CPU-only) and `ldspad_feasible`. The
overnight run command:

```bash
# CPU-only, from any session (safe under GNOME)
python3 check_candidates.py --quiet
python3 -m oto.harness.generate_candidates --dry-run
PYTHONPATH=. python3 oto/runners/cli.py --preflight

# TTY only — the real run
python3 port_tensile.py --auto --budget 10 --yes
```

Sizing: `phases.yaml` plus the seed overlay is what a run builds;
`python3 check_candidates.py --quiet` prints the live deck count and refuses
anything illegal. The last run took 13 h 14 m wall clock for 7.95 h of phase-busy
time, so ~12–14 h is the honest estimate. Judge **within-run only**, ≥3 seeds,
median, ±2% tie band.

---

Supersedes rewrite 2 (2026-10-14, kept below). **What was new in rewrite 3** is a
re-grading of the corpus under *every* A/B basis the repo can express, the
decoded gfx900 floor knob census, a verified hardware read for gfx90c, and one
live attribution bug that was hiding 8 of the 38 contract cells. The rewrite-2
findings (F1–F5) stand; the revisions below supersede their *numbers*, not their
mechanisms.

**Owns: the candidate deck, the routes to beat the spoof floor, and the search
rules.** Does not own: acceptance bars/ceilings/verdicts (`gfx90c_theoretical_limits.md`
§5), measured evidence (`results.md`), or GCN hardware facts
(`knowledge_base.md`).

---

## 0. Revision 3 — six findings that change the numbers, not the plan

### R0 — the verdict basis is inconsistent, and one path grades on the statistic
`ab_delta._stat` itself calls "seed-noisy, reference only".

Two graders exist in the tree and they do not agree:

| grader | statistic | used by |
|---|---|---|
| `ab_delta._pair_cells(..., agg="winner")` | **best per-kernel median**, both arms | `generate_acceptance_report` → `acceptance_report.json` |
| `ab_audit.audit` | **`r["GFLOPS"]` = max single raw sample**, both arms | other tooling |

`ab_delta._stat`'s own docstring ranks `best` (max raw sample) last: *"max single
raw sample (seed-noisy, reference only)"*. Grading a cell on best-of-many-draws is
an order statistic: **the more kernels an arm draws, the higher its expected max.**
The native arm carries 684–742 kernels per SS/HH cell; the spoof arm carries 26
for ZZ and 1166 for SS. That asymmetry is the whole content of some "wins".

The same data under every basis (`agg`, cells with both arms):

| basis | meaning | verdicts |
|---|---|---|
| `winner` (report) | native best-kernel vs spoof best-kernel | 38c: **29 W / 9 T / 0 L** |
| `median` | typical native vs typical spoof | 30c: **5 L / 3 T / 22 W** |
| `floor_best` | typical native vs spoof's BEST | 30c: **25 L / 3 T / 2 W** |
| `strict` | native worst vs spoof best | 30c: **30 L** |

**The five `median` losses are the real work list** (typical native → typical
spoof, %):

1. **CC:256 −63.6 %** (50.9 → 139.8) ← the only non-wall cell in the whole corpus
2. **SS:512 −46.4 %** (260.6 → 486.5, native ships 693 kernels, median = 30 % of its own winner)
3. **DD:256 −44.6 %** (34.7 → 62.7, 172 kernels, median = 41 % of winner)
4. **SS:256 −17.6 %** (74.7 → 90.7, 684 kernels, median = 18 % of winner)
5. **HH:256 −4.3 %** (156.7 → 163.7)

Read together: the *winner* on SS:512, SS:256, DD:256 is genuinely good (native
wins those cells outright on `winner`), but the surrounding 600+ kernels are junk
that drag the median to 18–41 % of the winner. **The deck is large enough that
its own winners are outliers inside it.** §7 (Rewrite 3) makes that actionable.

### R1 — an attribution bug was hiding 8 of 38 contract cells (fixed).

`oto/metrics/ab_records.py:phase_records` built records with
`analytics.aggregate_by_cell(...)`, which keys **(dtype, shape, fp)** — no family
dimension. `reporting._ab_records_from_csv` builds them with
`aggregate_by_cell_typecode(...)`, which keys **(dtype, shape, fp, family)** with
the §13.2 typecode-first resolver. Two consequences, both verified on the live
registry:

* HPA kernels have kernel typecode `HHS`/`HSS` → `family_from_kernel_name` returns
  `"HH"`; the HPA distinction lives *only* in the phase-level family stamp, which
  `_hpa_variant` reads off the explicit `family` field. With no `family` field the
  928 native HH_HPA + 717 HS_HPA rows and **5124 spoof HPA rows folded into HH**.
* Result: `arm_record_sets` → `_pair_cells` graded **30 cells, not 38** — the
  DB-hooked mutator was structurally blind to the `HH_HPA` 512/1024/2048/4096 and
  `HS_HPA` 512/2048 cells, and HH's medians were computed with HPA contamination.

Fixed (the typecode path plus `phase_family=extract_family_from_phase_id`), and
the contamination warning rate-limited to one line per (stamp, typecode) class —
the legacy `phase_auto_0_{S,Z}_*` pool would otherwise emit 100+ identical lines
per A/B load. After the fix:

| cell | native | spoof | Δ | note |
|---|---|---|---|---|
| HH_HPA 512 | 853.4 | 390.4 | **+118.6 %** | was invisible |
| HH_HPA 4096 | 1411.1 | 1277.8 | +10.4 % | was invisible |
| HS_HPA 512 | 820.4 | 384.4 | **+113.4 %** | was invisible |
| HS_HPA 2048 | 1388.9 | 1344.2 | +15.1 % | was invisible |
| HH_HPA 1024 | 1447.0 | 1445.5 | +0.1 % | TIE, at bar |
| HH_HPA 2048 | 1370.3 | 1381.1 | −0.8 % | TIE, at bar |

**HH_HPA is a 2.2× win that the mutator was never allowed to see.** Treat every
post-fix HH-family median as the new baseline; the pre-fix HH numbers in rewrite 2
§2 are contaminated.

### R2 — the twelve ORANGE cells: 11 are a yardstick artefact, 1 is real.

`acceptance_report.json` reports **0 RED / 12 ORANGE (<50 % of the family's
realistic ceiling)**. Investigated on the latest data — the user's reading is
correct: they are non-blockers, and they are *bad kernels in absolute terms while
native already beats the floor everywhere except one cell*.

| cell | native %ceil | spoof %ceil | native vs floor | verdict |
|---|---|---|---|---|
| CC:192 | 10.6 | 3.9 | 118.2 vs 43.2 | WIN +173.6 % |
| CC:256 | 18.8 | 19.0 | 210.8 vs 212.3 | **TIE −0.7 %** ← the real one |
| CC:512 | 28.4 | 27.6 | 318.0 vs 308.4 | WIN +3.1 % |
| CC:1024 | 30.8 | 26.0 | 344.0 vs 290.8 | WIN +18.3 % |
| CC:2048 | 31.0 | 26.1 | 346.7 vs 292.3 | WIN +18.6 % |
| ZZ:128 | 17.1 | 5.0 | 16.8 vs 4.9 | WIN +241.4 % |
| ZZ:192 | 21.1 | 15.0 | 20.8 vs 14.8 | WIN +40.7 % |
| ZZ:256 | 22.5 | 17.7 | 22.2 vs 17.4 | WIN +27.3 % |
| ZZ:512 | 24.3 | 20.9 | 23.9 vs 20.6 | WIN +16.2 % |
| ZZ:1024 | 24.7 | 22.9 | 24.4 vs 22.6 | WIN +7.8 % |
| HH:256 | 31.0 | 8.2 | 763.4 vs 202.0 | WIN +277.9 % |
| SS:256 | 36.8 | 11.1 | 412.0 vs 124.3 | WIN +231.5 % |

Eleven are cells whose *ceiling* is the wrong bar: complex families pay 4 real
FMAs per complex-MAC with no complex-FMA and no MFMA on this part, and 128³/256³
cubes physically cannot fill 7 CUs. Native is 1.1–3.8× the floor on all eleven.
**CC:256 is the single genuine shortcoming**, and it is the one cell where native's
*typical* kernel is also behind (§0 R0).

### R3 — gfx90c verified hardware read: 7 CUs, MFMA absent, WGM 8 is wrong.

§1 of `gfx90c_theoretical_limits.md` is the authority and is confirmed by the
research pass: gfx90c = ISA (9,0,12), **7 CUs / 28 SIMDs / 280 wave slots**, Wave64,
448 FP32 lanes, 1800 MHz, **LDS 64 KiB/CU**, L1 16 KiB/CU, L2 1 MiB, DDR4 UMA
~42 GB/s real. Tensile's own `AsmCaps.py` sets `HasMFMA: False` / `HasWMMA: False`
for ISA (9,0,0) and (9,0,6), so `SolutionStructs.py:3131-3134` **rejects
`EnableMatrixInstruction` outright**.

Two consequences the deck must act on:

1. **`MatrixInstruction` and `DirectToLds` are dead ends — record them, do not
   search them.** The whole ThreadTile→MFMA/VGPR-mapping literature is unreachable
   here. Worse, `DirectToLds` *blocks* `NumLoadsCoalesced > 1`, forces `GLVW=1` for
   8/16-byte dtypes, and forces `1LDSBuffer`. Every Draw spent on them is wasted.
2. **`WorkGroupMapping = 8` asks for 8 workgroups in the J-column before wrapping
   on a 7-CU part** — it is the floor's dominant value (1269 of 2285 shipped
   kernels) precisely because it was tuned for 56-60 CUs. The natural set for this
   hardware is `{1,2,3,4}` plus the **negative (I/J-swap) family** `{−1, −4}`, which
   the corpus has never generated at all.

The 7-CU occupancy cliff, per workgroups resident per CU
(`LDS = 2·(MT0+MT1)·DU·bpeAB`, budget 64 KiB/CU):

| config | LDS per WG | **WG/CU** |
|---|---|---|
| SS 128x128x8 | 16 KiB | 4 |
| SS 128x128x16 | 32 KiB | **2** |
| SS 128x128x32 | 64 KiB | **1** |
| DD 128x128x16 | 64 KiB | **1** |
| DD 128x64x16 | 32 KiB | 2 |
| HH 128x128x16 | 16 KiB | 4 |

At 256³ a 128×128 macro tile yields **4 workgroups for 7 CUs — 6 of 7 CUs idle.**
No knob tuning recovers that; the only levers are a smaller MacroTile, more
GlobalSplitU, or `LocalSplitU` (which fills waves *without* shrinking the tile —
rewrite 2 Route C's LocalSplitU note, now with the numbers above).

### R4 — the gfx900 floor's own knob census (2285 kernels decoded).

The floor (84 `.dat` entries → 2285 kernels,
`gfx90c_results/gfx900_shipped_manifest.json`) is **aggressive on tile geometry
and conservative on everything else**. Parameters with *zero* variance across all
2285 kernels: `LdsBlockSizePerPadA/B = 0`, `FractionalLoad = 2` (never emitted),
`PrefetchGlobalRead = 2` (never), `WaveSeparateGlobalRead = 0`,
`ThreadSeparateGlobalRead = 0`, `TransposeLDS = 0`, `UnrollMajorLDS = 0`,
`1LDSBuffer = 0`, `NonTemporal* = 0`, `PersistentKernel = 0`,
`GlobalReadPerMfma = 1`, `LocalWritePerMfma = −1`.

The padding asymmetry is the finding: **SS pads (LdsPadA=2 in 110 kernels,
LdsPadB=2 in 162, LdsPadB=4 in 55), HH pads in 17 — and DD, CC and ZZ never pad in
a single kernel.** Tensile's own `Perf/*.yaml` recipes likewise never enumerate
`LdsPadA/B`, `NumLoadsCoalesced`, `WaveSeparateGlobalRead`, `1LDSBuffer`,
`LocalWritePerMfma` or `GlobalReadPerMfma`. That is a **self-consistent blind spot
in both the vendor library and Tensile's recipes**, not a tuning decision — which
makes it the highest-yield untested axis for CC/ZZ/DD.

Also: `AssertFree0/1ElementMultiple` are 1 (no assertion) in essentially the whole
floor, while Tensile's own recipes set **8 for half, 4 for single, 2 for double**,
and every deck shape is divisible by 4 (all but 1000/1365 by 8). Setting them
unlocks `UseSgprForGRO` — which is the difference between 1 and 2 workgroups/CU on
a 256-VGPR part.

> **Correctness caveat, load-bearing:** `AssertFree*` is an *assertion*, not a hint.
> A wrong value produces **silently wrong results, not a crash**. Every AF-emitted
> row must be gated on exact shape divisibility (AF0EM = AF1EM = the largest power
> of two dividing both M and N; 1 for 1365) and the *first* AF row per cell must be
> validated against a reference GEMM before any of them is trusted.

### R5 — SOTA search strategy is a *budget-tiered* choice, and we are in the low tier.

From the TEVC 2022 Kernel Tuner study (arXiv:2210.01465 — 26 spaces × 9 GPUs ×
16 optimisers, GEMM in OpenCL on an AMD MI50):

| budget | what wins |
|---|---|
| ≤200 evaluations | **dual annealing**; Bayesian SMAC *"did not even beat random sampling for GEMM"* |
| 200–800 evaluations | first-improvement local search, simulated annealing |

Our per-configuration cost is a full Tensile generate + assemble + benchmark, so a
10-hour overnight is a few hundred evaluations at best: **we are squarely in the
low-budget regime.** The transferable conclusion is an **analytic pre-filter, then
first-improvement hill climbing**, *not* a surrogate model. Supporting: arXiv
2407.11488 finds AMD gains ~10× from autotuning where NVIDIA gains ~2×, and that
Nvidia-tuned configs do not transfer across vendors — i.e. honour the SS-pads /
DD-never-pads asymmetry above rather than averaging over it.

Practically, reorder §11's loop as: **prune by the analytic model first
(ceiling %, LDS WG/CU, TT-area × bpe) → hill-climb the surviving frontier
(1-knob deltas from the current winner) → only then draw diagonals.**

### R6 — two live wastes in the mutator's domain table (and one latent crash).

`oto/tensile/synthesis/db_knobs.py:FORWARD_KNOB_DOMAINS`:

| current | problem | fix |
|---|---|---|
| `GlobalLoadVectorWidthA/B: (1,2,4)` | `4 × 8 B = 32 B` (DD/C) and `4 × 16 B = 64 B` (Z) both break the verified **16-B global-load cap**. The gate catches them CPU-side, but each is a wasted *draw slot* — the mutator has only 5 draws per iteration. | `S:(1,2,4)`, `H:(1,2,4,8)`, `D/C:(1,2)`, `Z:(1,)` |
| `WorkGroupMapping: (1,4,8)` | misses the negative (I/J-swap) family and the small-box set; 8 is wrong for 7 CUs (R3). | `(1,2,3,4,−1,−4)` |
| `StaggerUStride: (0,256,512)` | Tensile silently raises `StaggerUStride` to a whole multiple of `DepthU × bpe`, so **`256` becomes 64** for DU=16/bpe=4. Most of the domain collapses to one point. | `(0,64,128,256)` — 64/128 are already legal in `STAGGER_STRIDE_DOMAIN` |

Plus a latent crash: `oto/tensile/synthesis/db_patterns.py` reads
`FORWARD_KNOB_DOMAINS["GSU"]` (twice) but the table keys it **`GlobalSplitU`** —
a `KeyError` the moment that branch is taken.

---

## 0.5 Rewrite 2 (2026-10-14) — kept in full below

### R7 — the deck-flood fix, and the new levers to spend the freed budget on

**The flood.** The native arm carries **684, 693, 742, 726, 668** kernels on
SS:256, SS:512, HH:512, HH:2048, SS:768 respectively — 30 cells, ~10 800 kernels
total, ~360 per cell. Their `median/winner` ratios are **18 % (SS:256), 30 %
(SS:512), 21 % (HH:256), 24 % (CC:256), 26 % (ZZ:128)**. A cell whose median is a
quarter of its own winner is a cell in which almost everything measured was junk:
near-duplicate mutants of a config already in the ledger, the same geometry
re-measured across seven runs, and the sweep-order defect of `results.md` §13.4.

That is not a tuning problem, it is an **allocation** problem: the deck spends
10+ hours producing draws the acceptance basis then cherry-picks. Two changes:

1. **Bound the population per cell.** Cap distinct kernels per (family, cell) so
   the frontier is the top-K by the analytic model, and let the DB mutator mutate
   only the *active* survivors. `check_candidates.py --floor` already proves the
   floor's 30 per-cell winners all pass every gate (todo 3 DONE), so the analytic
   pre-filter has a known-good reference set to imitate.
2. **Judge on a robust statistic, and report both.** The report should grade
   `agg="floor_best"` ("is a typical native kernel better than the floor's best
   kernel" — it *cannot* be won by cherry-picking one lucky config, because the
   native side is graded on its median) as a **co-primary** alongside `agg="winner"`.
   `ab_audit.audit`'s max-raw-sample basis should be dropped or renamed, since
   `ab_delta._stat` calls it reference-only.

**The new levers, ranked by expected payoff per GPU-minute.**

| # | lever | cells | mechanism | source |
|---|---|---|---|---|
| 1 | **`LdsPadA/B ∈ {1,2,4}` on CC, ZZ, DD winner geometries** | CC:256, ZZ all, DD:256 | GCN LDS = 32 banks × 4 B, `bank = (addr/4) mod 32`, wave64 serviced in 8 phases of 8 lanes; a 17.6 % gap means a second conflicting phase. The floor *never pads these families* — a blind spot in both the library and Tensile's own recipes. | R4 |
| 2 | **`AssertFree0/1ElementMultiple` = 4 (2 for double, 8 for half)** | all, gates exact shape divisibility | unlocks `UseSgprForGRO` (fewer VGPRs for addressing = the 1-vs-2 WG/CU step on a 256-VGPR part), removes shift/unshift code, widens tail-loop loads. Tensile's own recipes set exactly this; the floor ships 1 everywhere. | R4 |
| 3 | **MacroTile shrink + `LocalSplitU`** | SS:256/512, DD:256, HH:256 | 7-CU cliff: a 128×128 tile at 256³ is 4 workgroups for 7 CUs (57 %). `LocalSplitU` fills waves *without* paying the arithmetic-intensity cost of shrinking the tile. | R3 |
| 4 | **`WorkGroupMapping ∈ {1,2,3,4,−1,−4}`** | CC, HH_HPA, SS small | the negative (I/J-swap) family is never generated; WGM 8 is a 56-CU artefact. | R3/R4 |
| 5 | `FractionalLoad ∈ {0,1,2}` | SS, CC at 2048 | the only knob that changes load shape on non-divisible tails; the floor never emits 2. | R4 |
| 6 | `PrefetchGlobalRead ∈ {0,1,2}`, `PrefetchLocalRead 0/1` | all | PGR=2 never shipped; PGR=0 halves register pressure on VGPR-bound CC/ZZ. | R4 |
| 7 | `NonTemporalA/B ∈ {0,4,8}` | SS/HH 2048+ | avoids L2 (1 MiB) pollution on large squares; floor ships 0 everywhere. | R4 |
| 8 | `StaggerUStride ∈ {0,64,128,256}` | CC/ZZ/SS winners | 256 silently collapses to `DepthU × bpe`; 64/128 are live and already gate-legal. | R6 |

**Explicitly do NOT search** (R3): `MatrixInstruction`, `DirectToLds*`,
`WavefrontSize`. On gfx90c these are either `SolutionStructs`-rejected outright or
actively harmful (`DirectToLds` blocks `NLCA>1`, forces `GLVW=1` on 8/16-byte
dtypes, and forces `1LDSBuffer`).

### R8 — Route G: the CC:256 steal, with its port record (the one real shortcoming)

The user's caveat is honoured: **only CC:256**, the single non-wall cell, and only
because the floor already won the geometry there. Source is the locked gfx900
chain; the config was tuned for a 56-CU HBM part and is re-derived below.

**Stolen-from-gfx900** (`cells_resolved.json`, CC 256³):

| knob | floor winner | native winner today |
|---|---|---|
| `MacroTile` | **64 × 64** | 32 × 32 |
| `ThreadTile` | 4 × 4 | 4 × 4 |
| `VectorWidth` | 2 | 2 |
| `WorkGroup` | **16 × 16 × 1** | 8 × 8 × 1 |
| `WorkGroupMapping` | 4 | 4 |
| `GlobalSplitU` | 1 | 1 |
| `DepthU` | 8 | 8 |
| `GlobalLoadVectorWidthA/B` | **2 / 2** | absent (auto) |
| `LdsPadA` | 0 | 0 |
| measured | **212.34** | **193.77** (−8.7 %) |

Both kernels are `Ailk_Bjlk` (NT), so the gap is **pure tile area + load width**,
not contraction direction.

**The gfx900 → gfx90c port record** — what changes and why:

| knob | gfx900 value | gfx90c adaptation | why it changes |
|---|---|---|---|
| `MacroTile` 32×32 → **64×64** | 32×32 was native's own | **64×64, from the floor** | 4× the arithmetic intensity; LDS = `2·(64+64)·8·8 B = 8192 B/WG`, half the 16 KiB/WG budget |
| `WorkGroup` 8×8×1 → **16×16×1** | 8×8×1 | **16×16×1, from the floor** | `WG = MT/TT` self-consistently; 64 threads/WG keeps wavesPerCU legal |
| `GlobalLoadVectorWidthA/B` → **2/2** | absent | **2/2, from the floor** | `2 × 8 B = 16 B` sits exactly on the verified 16-B cap, so this is the widest legal global load for C — the one thing native's winner lacks |
| `StaggerU` 32 → **re-sweep 0/8/16** | 32 | 0/8/16 | 32 was chosen for a 56-CU raster order |
| `WorkGroupMapping` 4 → **probe {4, 8, −4}** | 4 | 4/8/−4 | CC:512 already prefers WGM8 within-run; the negative family is untested |
| `LdsPadA/B` 0 → **{1,2,4}** | 0 | 1/2/4 | CC never pads in the floor (R4); GCN bank math says the row stride, not the element |
| `AssertFree0/1ElementMultiple` → **4** | 1 | 4 | 256 is divisible by 4; unlocks `UseSgprForGRO`. **Gated on divisibility; verify against a reference GEMM first** (R4 caveat). |
| `PrefetchGlobalRead` → **{0,1}** | default 1 | 0/1 | CC is register-bound; PGR=0 relieves pressure |
| `LocalSplitU` → **probe {1,2}** | 1 | 1/2 | fills waves without shrinking the tile (R3) |
| `MultiBuffer` / `GlobalSplitU` | 1 | 1 | complex GSU is gate-refused on this port; LSU is the legal equivalent |

Only `MacroTile`, `WorkGroup` and `GLVW` are taken verbatim from gfx900 — all
three are *self-consistent consequences* of MT/TT/VW, not vendor magic numbers.
Everything else is re-swept because the part it was tuned for had 60 CUs and HBM2.

### R9 — everything from this point down is rewrite 2 (2026-10-14)

Everything from this point down is rewrite 2. It is superseded in its **numbers**
(the scoreboard, the tie causes, the per-cell winner table) by §0 above, and
retained in its **mechanisms** (Routes A–F, §8 legality matrix, §8.2 tiles,
§9 open decisions, §10 GUI-safe prep), which the revisions here extend rather than
replace.



---

## 1. Executive — five findings that change the plan

**F1. The spoof floor carries no clock telemetry, and that is a standing
property of the reference chain — not the cause of any single cell's verdict.**
`gfx90c_results/acceptance_report.json`: `spoof_clock_sclk_hz = 0.0`,
`spoof_clock_coverage = 0.0`, `clock_adjusted = False` on **every** cell, so no
verdict against the floor can be clock-corrected. Because the gap is uniform, it
cannot differentiate one cell from another and therefore explains no LOSS. The
only cell that ever read LOSS (CC 256³, run `run_20261013_214649`) was depressed
by a candidate-pool sweep-order defect, not by telemetry; the fix and the clean
re-run (`run_20261015_041159`, 19 W / 19 T / 0 L, CC:256 **TIE**) are in
`results.md` §13.4. Do not silently widen the band.

**F2. Two knobs in the deck have only ever held ONE value, across all runs and
both arms.** `allruns.py` (`--json`), never-exercised-knobs section:
`GlobalSplitU = ['1']`, `StaggerU = ['32']`. Additionally, no winning config in
`cells_resolved.json` sets `PrefetchGlobalRead`, `AggressivePerfMode`,
`MaxOccupancy`, `LocalSplitU`, `BufferLoad`, `InnerUnroll`, `FractionalLoad`,
`UseSgprForGRO`, `LocalRead2A/B`, `GlobalRead2A/B`, `StorePriorityOpt`,
`GlobalLoadVectorWidthA/B` or `NumLoadsCoalescedB`. **Every tuning conclusion
drawn so far is a conclusion about MacroTile × ThreadTile × DepthU ×
VectorWidth × WorkGroupMapping only.** The tile axes are mined out; the other
eleven axes are untouched.

**But "never set" ≠ "never varied".** Tensile fills every absent knob from
`defaultBenchmarkCommonParameters`, so the base already carries `BufferLoad=True`,
`StaggerU=32`, `MaxOccupancy=40`, `AggressivePerfMode=1`, `PrefetchGlobalRead=1`,
`UseSgprForGRO=-1`, `GlobalLoadVectorWidth=-1`, `InnerUnroll=1`,
`FractionalLoad=0`. The experiments are the *non-default* values; a sweep value
equal to the default re-measures the baseline. Verified defaults:
`knowledge_base.md` §7.1; machine-readable `TENSILE_KNOB_DEFAULTS` in
`oto/tensile/decks.py`, enforced by `tests/test_knob_sweep.py`.

**F3. The complex families are the two *narrowest* searches in the deck, which
is exactly backwards.** Measured distinct `(MacroTile, ThreadTile,
VectorWidth)` triples per family (`allruns.py`): SS 49 (16 distinct TT), HH 42
(12), HS_HPA 40, HH_HPA 36, DD 17 (7), **CC 17 (6)**, **ZZ 9 (5)**. CC and ZZ
are the worst performers AND the least searched. For CC the corpus only ever
emits ThreadTiles 2x2, 2x4, 4x2, 4x4, 4x8, 8x4 — and the *widest legal* corner,
**MT128x128x8 at TT8x4 and TT4x8, was never generated at all** (CC's largest
measured MacroTile is 128x64). For ZZ, **MT128x128x8/TT4x4 and MT128x64x8/TT4x4
are legal and were never generated** (the corpus's largest ZZ tiles are
128x32x16 and 32x128x16, both at 2x8).

The narrowness is partly structural, not lazy, and this decides what can be
tried: the legality gate caps the complex accumulator at
`ACCVGPR_BUDGET = 128`, so CC TT6x6 (144 accumulator VGPRs) and TT8x8 (256) are
refused with `Occupancy limit: ThreadTile 6x6 needs 144 accumulator VGPRs`, and
TT6x6 also fails `MacroTile 128x128x8 not divisible by ThreadTile 6x6`. Verified
through `validate_config`. **So the exploit is not a bigger ThreadTile — it is a
bigger MacroTile at the same accumulator width**, which raises arithmetic
intensity without touching the register file.

**F4. Occupancy is low, but not in the way the deck assumed — and the assumed
direction of the fix is inverted.** Measured from emitted code objects
(`python3 -m oto.harness.asm_occupancy`, 5757 kernels, GFLOP/s joined to 100%):
LDS strictly binds **61.7%**, VGPR strictly binds 22.4%, both cap identically in
15.9%; median 8 waves/CU; **121 kernels (2.1%) at ≤3 waves/CU**; 2810 (48.8%) at
≤3 *resident workgroups*/CU; **zero kernels spill to scratch**. The old deck's
M1/M2/M3 ("ALU saturation", "occupancy starvation", "VGPR pressure") is wrong in
its emphasis. Occupancy is *shape-limited*, not resource-starved, and the
binding constraint is LDS capacity — which is the one thing raising `ThreadTile`
makes worse.

**F5. Complex runs at 20–25% of an achievable ceiling that no tile in the legal
space can reach, and the reason is instruction count.** See §6. CC's best
measured kernel is 360.9 GF/s (MT64x64x8/TT4x4, 79 VGPR, 12 waves/CU) against a
1118.7 bar; ZZ's is 24.7 (MT32x32x8/TT2x2, 63 VGPR, 8 waves/CU) against 98.6.
The corpus's ridge table places the ALU ridge beyond the accumulator cap for Z.
**The gap is not closable by ThreadTile search alone** — which is why the deck
must spend its budget on the un-varied knobs and on the larger-MacroTile /
same-accumulator corner (F3), not on more ThreadTile widths.

---

## 2. Why each tie happens (per family, cause-coded)

Verdicts from `run_20261015_041159` (current): 19 WIN / 19 TIE / 0 LOSS. Reads as
"native already beats spoof" — and it does. But that is the wrong comparison: the
spoof floor is *also* mediocre on this part (CC 346.7 = 31% of ceiling). The real
gap in every family is **native vs. ceiling**, so §2 codes each family by what
limits it, and §8 targets that.

| family | verdict | best median | % ceiling | limiter | cause |
|---|---|---|---|---|---|
| CC | 3W/2T | 346.7 | 31.0% | **issue rate** | 4 real FMAs/complex-MAC, no complex-FMA opcode, no MFMA; 8 B/elem; ridge past legal TT (§6) |
| ZZ | 5W | 24.4 | 24.7% | **issue rate + VGPR** | 16 B/elem, 4 regs/elem → TT2x2 is the only tile with headroom; ridge at MT≈10, i.e. unreachable |
| HH | 2W/3T | 2749.3 | 111.7% | already at bar | — |
| HH_HPA | 2W/2T | 1447.0 | 129.4% | already at bar | — |
| HS_HPA | 2W/2T | 1441.2 | 128.8% | already at bar | — |
| SS | 2W/6T | 1187.2 | 106.1% | issue rate at high k | — |
| DD | 3W/4T | 98.0 | ~99% | at bar | — |

Cause codes for the 19 ties, individually:

- **CC:256 TIE** — was a candidate sweep-order defect (`results.md` §13.4), not a
  kernel deficit. Do not add candidates for it.
- **CC:512 TIE** — real, +3.1%. Winner MT64x64/WGM4+NLCA1; the deck's
  128x128-class tiles were never generated for CC, so this is unexplored space.
- **DD 768/1024/1365/2048 TIE** — all ≤2.2%. DD's best measured kernel is
  99.9 GF/s at MT32x32x8/**TT2x2**, 35 VGPR, **28 waves/CU** — the highest
  occupancy in the corpus. DD is at its 98.6 bar already; residual gap is
  issue rate.
- **HH 1024/2048/4096 TIE** — +1.3 to +3.7%. HH's best is 2922.8 at
  MT128x128x16/TT8x8, 63 VGPR, 16 waves/CU. HH already exceeds its 2461 bar.
- **HH_HPA / HS_HPA 1024/2048 TIE** — −0.8% to +3.3%. At bar.
- **SS 768/1000/1024/1365/2048/4096 TIE** — +0.9% to +4.6%. SS's best measured
  is 1340.5 at MT128x128x8/TT8x8, 111 VGPR, 8 waves/CU; SS:4096 already exceeds
  its 1118.7 bar. **The residual SS gap is entirely in the small-shape rows**
  (k=32: 276.1 = 24.7%; k=192: 341.8 = 30.6%), which is wave quantization, not
  issue rate.

---

## 3. Occupancy — settled, and it is not the deck's problem

`python3 -m oto.harness.asm_occupancy --check-calibration` exits 0 (10/10 rows
of the AMD/ORNL GFX9 VGPR→waves/SIMD table reproduced, granule 4). The corpus
wide numbers above are from that model. Three consequences:

1. **There is no occupancy-starvation problem to fix.** Only 2.1% of kernels run
   at ≤3 waves/CU. The 48.8% figure the user noticed is *resident workgroups*,
   which is a different axis (a 1024-thread workgroup is 16 waves, so it reads
   as "1 workgroup" while occupying 16 of 40 wave slots). Both numbers are in
   `gfx90c_theoretical_limits.md` §7.1.
2. **LDS capacity, not VGPR, is what caps residency** for 61.7% of kernels —
   which is why the `LDS_BUDGET` entry (§10) matters and why `LdsPad`/
   LDS-layout angles are deprioritised: bandwidth is ~8× oversupplied at
   TT4x4 FP32 (`knowledge_base.md` §1 rate card), but *capacity* still decides how many
   workgroups fit, and `LdsPad` spends that capacity.
3. **No kernel spills.** Zero kernels carry a private segment. So there is no
   scratch-spill tax to recover, and `MinVgprNumber`/`MaxVgprNumber` tuning has
   no measured motivation.

---

## 4. Kernel-type patterns across all runs (the high-level answer)

From the 5757-kernel table, ranked by best measured GFLOP/s per family:

| family | best tile | TT | VGPR | waves/CU | LDS | best GF/s |
|---|---|---|---|---|---|---|
| H | 128x128x16 | 8x8 | 63 | 16 | 16384 | 2922.8 |
| S | 128x128x8 | 8x8 | 111 | 8 | 16384 | 1340.5 |
| D | 32x32x8 | 2x2 | 35 | 28 | 8192 | 99.9 |
| C | 64x64x8 | 4x4 | 79 | 12 | 16384 | 360.9 |
| Z | 32x32x8 | 2x2 | 63 | 8 | 24960 | 24.7 |

The pattern, stated as a rule: **the winning ThreadTile area scales inversely
with bytes-per-element.** 2 B → 8x8; 4 B → 4x4–8x8; 8 B → 4x4; 16 B → 2x2. That
is the accumulator register budget: `TT_area × bytesPerElement` must stay under
~64 accumulator VGPRs to leave room for A/B fragments and addressing. Every
family's winner sits at the largest TT satisfying that rule. **This is why CC
and ZZ are stuck: their rule-implied TT (4x4 and 2x2) is already the winner, and
the next step up breaks the register file.**

Second pattern — **waves/CU does not predict GFLOP/s.** D wins at 28 waves/CU
and H at 16, but C's 12 beats Z's 8 despite occupancy close to 2/3rds. What
predicts GFLOP/s is `bytesPerElement` × `flopsPerMac`, i.e. how much work each
FMA issue buys, which is fixed per family and not a knob.

Third — **LDS at the winner is always ≈16–25 KB, never 64 KB.** The winners
operate at 1/4 to 1/3 of the 64 KB LDS budget, i.e. 2–4 resident workgroups.
That is the architectural sweet spot for this part.

Fourth — **`WorkGroupMapping` is 4 or 8 at every winner, never 1.** WGM≥4 is
what keeps neighbouring CUs on the same matrix B slice, which matters because
L2 is 1 MB shared. No winner uses WGM 2 or 16.

---

## 5. Physics — why complex cannot reach its ceiling, and what that implies

Ridge for a tiled kernel (not the minimum-traffic figure the previous roofline
used):

```
AI = flopsPerMac · MT0·MT1 / ((MT0 + MT1) · bytesPerElement)
```

| family | bytes/elem | peak | ridge (F/B) | square MT at ridge | legal TT at that MT |
|---|---|---|---|---|---|
| S | 4 | 1613 | 38.4 | 154 | 8x8 ✓ |
| H | 2 | 3226 | 76.8 | 154 | 8x8 ✓ |
| D | 8 | 101 | 2.4 | 19 | 2x2 ✓ (already ALU-bound at MT≥32) |
| C | 8 | 1613 | 38.4 | 77 | 4x4 ✓ (MT77 needs MT≥96 to cross) |
| Z | 16 | 101 | 2.4 | 9.6 | 2x2 ✓ (ALU-bound everywhere) |

Two families are already past their ridge and still at 20–25% of ceiling: that
is the proof that **complex is issue-bound, not bandwidth-bound**. The
instruction-count argument: one complex MAC is four real FMAs and there is no
complex-FMA or MFMA opcode on gfx90c. Complex-MAC *throughput* is ÷4 relative to
a real MAC, but BLAS-8 accounting credits 8 flops per complex MAC, so the BLAS
ceiling is unchanged (`oto/tensile/gates/assembly.py`). Reaching it needs the
FMA pipe issuing every cycle, which needs the issue slots not spent on
addressing, LDS reads and loop overhead.

**Implication for the deck:** for C and Z the only levers that reduce
non-FMA issue slots are (a) more coalesced loads (`NumLoadsCoalescedA/B`),
(b) longer unroll (`InnerUnroll`, `DepthU`), (c) `UseSgprForGRO` — moving
global-read addresses from VGPR to SGPR frees registers, which is the scarce
resource for Z. Tiles are exhausted.

---

## 6. The routes (steal + alternatives)

### Route A — Spoof-steal, restricted to the two worst losers, with a port record

Sanctioned per the user's own caveat: **only CC and ZZ**, only the worst cells,
and each stolen config must be documented as derived-from-gfx900 with its
adaptation. gfx900 floor configs used verbatim (~1100 phases of the locked
chain) were tuned for a 56-CU HBM part; the three that must be adapted are
tile size (HBM-optimal tiles overshoot a 1 MB L2), `WorkGroupMapping` (tuned
for 56-CU raster order, not 7), and `GlobalSplitU` (a dGPU never needed it).

Restriction: **only MT64x64 and smaller may be stolen.** gfx900's rank-1
solutions cluster at MT 64x64 and below, and those are also the correct class for
a 1 MB L2. An MT128x128 gfx900 tile would be stealing a config tuned for a part
with ~16× the L2. **AMD's shipped library is not uniformly small-tiled** — the
same vega10 tree holds MT128×16 (FP32), MT064×064 (FP64) and MT016×016 (FP16) —
so "AMD prefers small tiles" is not a supportable generalisation; only the
*rank-1* rows are small, and those are the ones that transfer
(`kernel_tuning_research.md` §9.1).

**The port record.** AMD's own rank-1 solutions for the sibling Vega parts
(gfx906/gfx900, wave64, 64 KB LDS/CU — the same data-path shape as this part with
60 CUs and ~900 GB/s HBM2 instead of 7 and 42 GB/s), from
`kernel_tuning_research.md` §9.1:

| source family | rank-1 tile | TT | DU | WorkGroup | VW | BufferLoad | PGR | PLR | APM | MaxOcc |
|---|---|---|---|---|---|---|---|---|---|---|
| FP32 (`vega10…SB`) | 128x016 | 4x4 | 16 | 32x4x2 | 4 | 1 | 0 | 1 | 1 | 40 |
| FP64 (`vega20…DB`) | 064x064 | 4x4 | 4 | 16x16x1 | 2 | — | — | — | 1 | 40 |
| FP16 (`vega20…HB`) | 016x016 | 2x2 | 8 | 8x8x1 | 2 | — | — | — | — | 40 |

What transfers, and what must be re-derived for gfx90c:

| knob | AMD's gfx900 choice | keep / adapt for gfx90c | why |
|---|---|---|---|
| `ThreadTile` | 4x4 (FP64), 2x2 (FP16) | **keep** — matches this part's own measured winners (DD 2x2, ZZ 2x2) | accumulator register budget is a function of bytes-per-element, which is identical |
| `DepthU` | 4 (FP64), 8 (FP16) | **adapt down** — 16 (FP32's) would need 2× the LDS on a part with 1/60th the bandwidth | LDS capacity is the binding constraint here (61.7% of the corpus) |
| `WorkGroup` / `LocalSplitU` | `32x4x2` = LSU 2 on FP32 | **keep the LSU shape** — AMD itself splits the M extent | LSU is the one wave-fill knob legal for this part's complex families; `GlobalSplitU` is not (§8.1) |
| `StaggerU` | 32 | **re-sweep** 0/8/16 — 32 was chosen for a 56-CU raster | §8.1 sweeps it |
| `WorkGroupMapping` | (not overridden) | **re-sweep** 4/8 — this part's winners use 4 or 8 | 7 CUs with 1 MB L2 wants neighbours on the same B slice |
| `MaxOccupancy` | 40 (uncapped) | **re-sweep** 8/12/20 | 100% of shipped AMD uses 40; on 7 CUs wave count is scarcer |
| `AggressivePerfMode` | 1 | **re-sweep** 1/2 | mode 2 *may* cap LDS (comment says 2 waves/SIMD; branch unconfirmed at pinned commit — corpus3 Q-E ii), and 2 waves/SIMD is this part's measured median |
| `BufferLoad` | 1 (FP32) | **keep** | gates the StaggerU path |

The concrete stolen cells are the deck entries in §8.2 — the ones that exist only
because the floor won there and native never generated the tile.

### Route B — Pick up the ten knobs the corpus never *explicitly set* (highest yield, no steal)

§F2. **"No winner sets knob X" is not "knob X has never been varied."** Tensile
fills every absent knob from `defaultBenchmarkCommonParameters`, so several of
these are already active at a fixed value, and only their *non-default* values are
experiments. The verified default for each is in `knowledge_base.md` §7.1;
`TENSILE_KNOB_DEFAULTS` in `oto/tensile/decks.py` is the machine-readable copy, and
`tests/test_knob_sweep.py` refuses a sweep row that offers no non-default value.
Concretely, per family, with the reason:

| knob | who | why |
|---|---|---|
| `NumLoadsCoalescedA/B` | C, Z | default 1; one phase in the entire corpus sets NLCA. |
| `UseSgprForGRO` | Z | default `-1` (auto). Z is VGPR-bound at TT2x2 (63 VGPR); moving GRO offsets to SGPR buys VGPR. Requires `BufferLoad=1`, which is the default. |
| `PrefetchGlobalRead` | S, C | default 1. The corpus has both `None` and explicit `False`; the experiments are 0 and 2, with 1 as the control. |
| `AggressivePerfMode` | all | default 1. Mode 2 is *described as* a 2-waves/SIMD LDS cap, but the explicit branch is unconfirmed at the pinned commit (corpus3 Q-E ii) — the row tests whether mode 2 differs at all; `gfx90c_theoretical_limits.md` §7 puts the corpus median at 8 waves/CU = 2 waves/SIMD, so a real cap would be a free experiment in that direction. |
| `MaxOccupancy` | all | default 40 (uncapped). Lower values pad per-workgroup LDS to `DeviceLDS // N` (floor) — a pure occupancy clamp. |
| `LocalSplitU` | S, H at small k | default 1. Splits the MTA M extent across waves without a reduction kernel. `validate_config` accepts it for every family, so it is legal for complex on this gate. |
| `FractionalLoad` | S, C at 2048 | default 0; the only knob that changes the load shape for the non-divisible tails. |
| `GlobalSplitU` | S at k≤192, D at small k | default 1. **7-CU wave quantization**: `G = ceil(M/MT)·ceil(N/NT)`; at N=256, MT128 → 4 tiles on 7 CUs = 57% utilisation, MT32 → 64 tiles = 91%. GSU multiplies G, so it is the correct fix for the small-shape rows. |
| `InnerUnroll` | C, Z | default 1; directly reduces the fraction of issue slots spent on loop control. |

`BufferLoad` was on this list and is **not** a deck entry: its default is already
`True`, so sweeping `BufferLoad: True` re-measures the baseline. An explicit `False`
is the only real change and it also kills the `StaggerU` path, which confounds it.
Recorded, not swept.

`GlobalLoadVectorWidthA/B` is **not** a deck entry as an unpaired row (§9 D4):
unpaired, the only values Tensile will build are `1` and `== VectorWidth` (the pv
reduction also cancels a widen on most tiles). A *paired* widen — `GLVW=2` with
`AssertFree0/1ElementMultiple=2` — is legal for CC only, and *is* swept as a
trial (added 2026-10-14). See §8.1.

### Route C — Wave-quantisation ladder (small shapes only)

`GlobalSplitU` × tile-size pairs chosen so `G·S` lands near a multiple of 7.
Enumerate: for each cell, for `MT ∈ {16,32,64}` and `S ∈ {1,…,7}`, keep the pairs
where `G·S mod 7` is 0 or 1. This is a *narrow* route — few candidates, all in
the quantisation-optimal band.

**The arithmetic** (`G = ceil(M/MT) × ceil(N/NT)` tiles on 7 CUs; utilisation =
`G / (7 × ceil(G/7))`):

| problem | MT | G | G mod 7 | aggregate utilisation |
|---|---|---|---|---|
| 128x128 | 16x16 | 64 | 1 | 91.4% |
| 128x128 | 32x32 | 16 | 2 | 76.2% |
| 128x128 | 64x64 | 4 | 4 | 57.1% |
| 128x128 | 128x128 | 1 | 1 | 14.3% |
| 256x256 | 32x32 | 64 | 1 | 91.4% |
| 256x256 | 64x64 | 16 | 2 | 76.2% |
| 256x256 | 128x128 | 4 | 4 | 57.1% |
| 512x512 | 64x64 | 64 | 1 | 91.4% |
| 512x512 | 128x128 | 16 | 2 | 76.2% |
| 1024x1024 | 64x64 | 256 | 4 | 98.8% |
| 1024x1024 | 128x128 | 64 | 1 | 91.4% |
| 2048x2048 | 128x128 | 256 | 4 | 98.8% |

Three things this table settles, and they are counter-intuitive:

1. **MT128x128 at 256³ runs 4 tiles on 7 CUs = 57% of the machine**, while MT32x32
   runs 64 = 91%. The tail is not a rounding error at small N; it is a 34-point
   swing.
2. **The penalty vanishes by N ≥ 1024** (98.8% at MT64x64), so Route C applies to
   the small-shape rows only. Spending the budget on quantisation for 1024³+ is
   wasted.
3. **A bigger tile is *worse* for utilisation at small N but *better* for
   arithmetic intensity** — these pull in opposite directions, which is why the
   small-shape rows (SS k=32 at 24.7% of ceiling, SS k=192 at 30.6%) are hard and
   why `LocalSplitU` is the interesting knob: it fills waves **without** shrinking
   the tile, so it does not pay the arithmetic-intensity cost that MT16x16 does.

Route C is legal **only for SS and DD** (±8.1). For CC/ZZ/HH/HPA the equivalent
fix is `LocalSplitU`, or nothing.

### Route D — LDS-capacity ladder for Z

Z is the only family where the winner already uses ~25 KB LDS and still binds
LDS. Drop `DepthU` 16→8 and 8→4 to free capacity for a second resident
workgroup, and/or `LdsPad` 0 (deprecated, never spent). Z's LDS at the winner is
24960 B — 38% of the CU — so one more workgroup costs the remaining 62%.

### Route E — Split-complex (the "3 real GEMMs" route)

Carried forward from the previous rewrite and still unmeasured. Reported split
GFLOPS = (4/3)·R_real for CC (3 real GEMMs under BLAS-8), ≈1513; and
(4/3)·95–98 ≈ 127–131 for ZZ. This is the only route that can *beat* the
1613/101 BLAS ceiling rather than approach it, because it removes the
complex-MAC instruction penalty entirely. It needs a harness change (a
decomposed call sequence, not a Tensile solution), so it is a separate work
item, not a deck entry. **Unmeasured — treat as hypothesis.**

### Route F — Persistent-kernel / fixed-grid route

gfx90c has 7 CUs. A fixed 7-workgroup grid eliminates tail-wave idle by
construction. Tensile cannot express this (`WorkGroup` sizes the grid, not the
occupancy), so this is a conceptual route for the kernel-writer, not a deck
entry. Listed so it is not re-proposed as a knob.

---

## 7. What to stop doing

Ceasing: **ThreadTile** width ladders for C and Z (F3/F5 — the accumulator cap
makes every wider tile illegal, so they are pure rejects); `LdsPad`/LDS-layout
work (`knowledge_base.md` §1 rate card — bandwidth ~8× oversupplied, and LDS *capacity*
is better spent on residency); any `-mllvm -amdgpu-*` or compiler-flag proposal
(no-op: Tensile emits ISA text to the assembler for ~93% of the shipped
library); `MaxOccupancy`/`AggressivePerfMode` *assumptions* without a
measurement (§F2 — never swept).

Now *starting*: MacroTile ladders for C and Z at the **existing** accumulator
width (F3). That is the opposite direction to a ThreadTile ladder and it is the
one the physics asks for.

---

## 8. The concrete deck additions

Every entry below was checked through `validate_config` (CPU-only) and reported
`Valid`; the rejections found along the way are recorded so they are not
re-proposed. Entries land in `oto/tensile/decks.py` `FAMILY_DECKS`, which is
where the generator reads them.

### 8.1 Legality matrix for the un-varied knobs (measured, 2026-10-14)

Each surviving sweep entry was checked as `the family's current winner tile +
the one knob change`, with the row's `width_override` applied where it has one
(NLCA needs it). Result: **every emitted cell is legal — 69/69 row×family
cells.** The ✗ cells below are knob/family pairs the deck deliberately does not
name, and each is a real, measured refusal.

| knob | CC | ZZ | SS | HH | DD | HH_HPA | HS_HPA |
|---|---|---|---|---|---|---|---|
| `NumLoadsCoalescedA/B=2` | ✓(vw1) | ✗ | ✓(vw1) | ✓(vw2) | ✗ | ✗ | ✗ |
| `UseSgprForGRO` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `PrefetchGlobalRead` 1 / 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `AggressivePerfMode` 1 / 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `MaxOccupancy` 8 / 12 / 20 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `LocalSplitU=2` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `StaggerU` 0/2/4/8/16/32 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `FractionalLoad=1` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `InnerUnroll=2` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `NonTemporalA/B` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `GlobalSplitU=2/4` | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ |
| `GLVW=2` + `AF0/1EM=2` (paired) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

Two hard results worth stating plainly:

- **`GlobalSplitU` > 1 is illegal for every half and complex family on this
  repo's gate** — `Assembly class: GlobalSplitU=2 on complex C: illegal`, and
  the same for `half Assembly` and `half with f32 acc`. Only SS and DD may
  split K. This kills the wave-quantisation fix for HH/HPA at every small
  shape, and it means Route C applies to SS and DD only.
- **`NumLoadsCoalesced=2` needs the right width**: legal at CC vw1 (not vw2),
  SS vw1/vw2 (not vw4), HH vw2, and never for ZZ/DD/HPA. The rule is
  `NLCA ≤ NumLoads` where `NumLoads` comes from the width, so the deck entries
  pair the width with the coalesce count rather than assuming both.
- `StaggerU` is legal at *every* value with and without `BufferLoad`, so it is
  free to sweep — and it is currently pinned at 32 corpus-wide (§F2).

Two caveats that are **not** in this matrix:

- **`BufferLoad` is not a deck entry.** Its Tensile default is already `True`
  (`knowledge_base.md` §7.1), so `BufferLoad=True` re-measures the baseline. It
  was removed from `KNOB_SWEEPS` on 2026-10-14.
- **`GlobalLoadVectorWidth` is no longer a deck entry (§9 D4, resolved 2026-10-14).**
  The gate models Tensile's *whole* rule, not just its first half: `GLVW !=
  VectorWidth and != 1` is refused **only when** `not bufferLoad or not
  GuaranteeNoPartialA`, where `GuaranteeNoPartialA` is
  `AssertFree0ElementMultiple % GLVW_A == 0` on a `TLUA` operand
  (`SolutionStructs.py:4584-4596` and `:4177-4183`), and `bufferLoad` is true only
  for a `KernelLanguage: Assembly` kernel. That is the branch the reference-rerun
  hashes `7f866dcf` / `a0edeb30` died on. With the default
  `AssertFree0ElementMultiple=1`, an *unpaired* `GLVW=2` is **refused** for
  CC/SS/HH/HPA and a **no-op** for ZZ (the pv reduction cancels it back to 1) and
  DD (already the derived default) — so the row was removed.
  
  The widen **is** realizable as a *pair*: `AssertFree0ElementMultiple=2` lifts
  `GuaranteeNoPartialA`, and where the pv reduction does not cancel it that is a
  real 8 B → 16 B load. Measured on the gate, that is **CC only** (VW1, pv=1); ZZ
  pv-cancels it, and for SS/HH/HPA (VW4) the pair is a *narrow*, not a widen. The
  paired CC row is swept as a trial (added 2026-10-14, §9 D4). Home:
  `oto/tensile/gates/loads.py` `_glvw_for` + `_Operand._restriction_active`,
  `tests/test_occupancy_gate.py::TestGlobalLoadVectorWidthRule`.

### 8.2 Tiles that are legal but were never generated (the real CC/ZZ headroom)

| family | MacroTile | ThreadTile | VW | why this corner |
|---|---|---|---|---|
| CC | 128x128x8 | 8x4 | 1 | widest legal accumulator (128 VGPR); AI 64 F/B = 167% of ridge; never generated |
| CC | 128x128x8 | 4x8 | 1 | transposed form of the above; never generated |
| CC | 128x96x8 | 8x4 | 1 | between the measured 128x64 and the unmeasured 128x128 |
| ZZ | 128x128x8 | 4x4 | 1 | AI 32 F/B = 13× ridge; never generated |
| ZZ | 128x64x8 | 4x4 | 1 | asymmetric, never generated |
| ZZ | 64x64x16 | 4x4 | 1 | longer unroll at the same width; never generated |
| DD | 128x128x8 | 8x8 | 1 | DD TT8x8 is legal (unlike CC); AI far past its 2.4 F/B ridge |
| DD | 64x128x16 | 4x8 | 1 | legal and never generated |

`StaggerU` 32 is the current constant; the sweep adds 0/8/16 to test whether the
7-CU geometry wants a different raster.

### 8.3 Route E and Route F are not deck entries

Route E (split-complex, 3 real GEMMs) and Route F (persistent fixed grid)
cannot be expressed as Tensile solution knobs — E needs a decomposed call
sequence in the harness, F needs a kernel-writer change. They are recorded in
§6 so they are not re-proposed as knobs, and are tracked as separate work items
(`incomplete_work.md`), not as deck rows.

---

## Sources

All numbers in §1–§8 are reproduced by repo tooling, which is the citation:
`allruns.py` (knob census, tile triples), `oto.harness.asm_occupancy` (5757-kernel
measured occupancy + GFLOP/s join), `oto.harness.resolve_cells` (per-cell
winners), `oto.harness.occupancy_audit` (predicted residency), `validate_config`
(§8.1's legality matrix), and `gfx90c_results/acceptance_report.json` run
`run_20261013_214649`.
Architecture/ridge facts: `knowledge_base.md`, `gfx90c_theoretical_limits.md`.
Anti-transfer: arXiv:2505.03780, arXiv:2507.15277 (`kernel_tuning_research.md` §6).

---

## 9. Open decisions (user-owned; do not act on these silently)

**D1 — CC:256's former LOSS closed as a candidate sweep-order defect
(resolved 2026-10-15).** The candidate pool emitted `ProblemSizes`
lexicographically (`1024, 192, 2048, 256, 512`), so 256³ was measured
immediately after the 2048³ kernel and its median absorbed the throttled clock
(`claude.md` §2.0.3). The clean re-run (`run_20261015_041159`) reads CC:256 as
**TIE** — native `210.772` vs floor `214.882`, −0.74 %. The floor arm still
carries no telemetry (`spoof_clock_coverage = 0.0`), so `clock_adjusted = False`
on every cell — a standing property of the reference chain, not a closure path
for this cell. Do not close it by widening a band; the verdict logic is not ours
to change.

**D2 — `BYTES_PER_ELEMENT["Z"]` vs `LDS_BUDGET`** (full record and measurement in
`gfx90c_theoretical_limits.md` §6.1). Tensile's complexDouble is `'reg': 4` so
`numBytes() = 16`, and the same module already has `FAMILY_BYTES_PER_ELEMENT
["ZZ"] = 16` — three tables in one file say 16, one says 8, and ZZ is the only
family where the gate's byte count is half of Tensile's element width.

The 8 is **not** an over-admission: measured, 0 of 229 ZZ kernels that built and
ran exceed the 16384 budget at that reading, so the gate never wrongly let a ZZ
config through. What it does is understate ZZ's real LDS pressure by 2× on the
base footprint (the gate says 16384 where Tensile allocates 65536 for a 64x64x16
tile). Correcting the bytes alone refuses **67 of those 229** kernels, so the
baseline `"Z": 16` with budget 32768 must be decided as a pair.

**D3 — should the ZZ deck's 24.9 KB LDS winners be re-checked against the
`LDS_BUDGET` gate after D2?** If D2 lands, ZZ's own winners (24960 B base,
65536 B emitted) move above the budget. The deck generator refuses candidates the
append boundary judges illegal, so this can silently empty the ZZ deck. Resolve
with D2.

**D4 — the sweep deck's baseline and the paired widen (resolved 2026-10-14; D1–D3
trial tiles added the same day).**

*Baseline: explicit control, opt-in.* `generate_knob_sweep_phases` gains
`include_baseline`, and `knob_sweep` gains `--baseline`: the base tile is emitted
unchanged once per (family, pattern, shape), tagged `_base`, so every knob delta
has a same-run control. Default off (the implicit default-as-control rows
`PrefetchGlobalRead=1` / `AggressivePerfMode=1` still exist); the run book (§10)
passes `--baseline`.

*Paired CC widen: added as a trial row.* `GLVW=2` **with**
`AssertFree0/1ElementMultiple=2` is a real 8 B → 16 B load and is legal for CC only
(VW1, pv=1); ZZ pv-cancels it and for SS/HH/HPA it is a narrow. CC is the worst
family (31% of its ceiling) and issue-bound. It is a `KNOB_SWEEPS` row
(`GlobalLoadVectorWidth`, CC-only) — not a clean one-knob change
(`AssertFree0ElementMultiple=2` asserts `M % 2 == 0` and reaches other Tensile
paths), so it is labelled a trial and the run judges it. §8.1 matrix +1 (69/69).

*D1–D3 trials: `DECISION_TRIAL_TILES` + `--trials`.* Three decisions are not knob
changes, so they own tiles instead of rows (emitted unchanged, tagged
`_trialD<n>`; `generate_decision_trial_phases`):
- **D1** — CC `64x64x8/4x4/VW2` (the steal geometry) at `192`/`256`, the shallow
  cells CC:256 owns. The candidate re-measures; the sweep-order fix
  (`results.md` §13.4) and the clean re-run close it.
- **D2** — ZZ `64x64x16/4x4/VW1` (the LDS-boundary tile). A ZZ VW2 "differentiator"
  row was decked and withdrawn the same day: Tensile's own `numBytes()` for
  complexDouble is 16, so `2 × 16 > 16` and Tensile refuses the phase at solution
  construction. `consolidate_deck.dtype_bytes` already reads that value from
  Tensile, and `tests/test_consolidate.py::TestLegalityGate::
  test_gate_catches_a_real_archived_zz_phase` locks the refusal against the
  archived deck — so the load-width half of D2 is settled by measurement and
  admits no trial. The budget half is what the boundary tile tests.
- **D3** — ZZ `128x128x8/4x4` and `128x64x8/4x4` (§8.2, never generated): the deck
  stays non-empty under either D2 reading.

No gate or verdict logic changed for any of this; the trials are *candidates*,
and the run decides. Dry-run: 246 sweep + 14 baselines + 8 trials = 268, 0 refusals.
Every candidate must pass **both** the append gate and
`consolidate_deck._is_legal`, which reads dtype bytes from Tensile itself rather
than from `BYTES_PER_ELEMENT`; `tests/test_knob_sweep.py::
test_no_emitted_candidate_passes_only_the_lenient_gate` enforces it.

*Resolved earlier (2026-10-14):* `GLVW=2` is not merely "maybe refused" — the gate now
models Tensile's shift-ptr rule in full, including the `GuaranteeNoPartialA`
escape hatch, so an *unpaired* `GLVW=2` is refused for CC/SS/HH/HPA and a no-op for
ZZ/DD. The unpaired row was removed. See §8.1 and
`oto/tensile/gates/loads.py::_glvw_for`.

---

## 10. GUI-safe prep for the 10h+ overnight run

Constraints: full Tensile benchmark runs are TTY-only and the user's to
launch. Agent work is CPU-only — deck generation, dry-run, gate checks.

1. **Deck** — `oto/tensile/decks.py` `FAMILY_DECKS` gains the §8.2 tiles and the
   §8.1 knob sweeps. Every entry is gated by `validate_config` at the append
   boundary, so an illegal row costs a rejection, never a crashed run.
   Emit with trials and controls:
   `python3 -m oto.tensile.knob_sweep --emit --baseline --trials`
   (dry-run default; 246 sweep + 14 baselines + 8 trials = 268, 0 refusals).
2. **Dry-run** — `python3 -m oto.tensile.candidate --dry-run` (or
   `check_candidates.py --deck <deck>.yaml`) to confirm the phase count and that
   no entry is silently dropped.
3. **Legality PoC only** — verify the new ZZ deck is non-empty after D2 lands
   (§9, D3). This is the one interaction that can empty a family.
4. **Clock hygiene** — pin the sclk level via sysfs
   (`power_dpm_force_performance_level` = `manual`, then `pp_dpm_sclk`), 25%
   warmup, L2 flush between repeats for memory-bound shapes, log median clock +
   temperature per phase, and interleave a reference kernel to detect drift.
   Full protocol: `knowledge_base.md` §8.3. Without this the run repeats the F1
   artifact.
5. **Budget split** — the never-varied knobs (§8.1) are the high-yield spend;
   tile ladders (§8.2) are the second; Route E is a separate work item and gets
   no time here.
6. **Post-run read guide (corpus3 Q-E iii).** PGR 0/1/2 is measured on the
   complex winners in this run — read the winner through LDS bytes, VGPRs and
   load/wait counts, not the mode number: **0 wins** = buffering costs exceed
   overlap (consistent with issue-bound); **1 wins** = one stage suffices;
   **2 wins** = look-ahead matters on that shape (not a universal PGR=2 rule).
   APM 1-vs-2 is read through the LDS allocation diff first (cap unconfirmed).

The pass-3 brief (Q-A…Q-F) is folded; residual follow-ups are §9.4 of
`kernel_tuning_research.md` and the protocol deltas are `knowledge_base.md`
§8.3. The prompts themselves are archived at `archive/RESEARCH_PROMPT*.md`.

---

## 11. The 10 h+ overnight run — runbook (2026-10-16)

Everything below is CPU-verified. Real benchmarking happens in the USER's TTY,
never from this GNOME session (`gfx90c_tuning_guide.md` §10.1).

### 11.1 The honest scoreboard first

Do **not** read the headline `19 WIN / 19 TIE / 0 LOSS` as "the floor is
beaten". That number grades on `agg="winner"` = **best per-kernel median**, which
is an order statistic: the arm that draws more kernels has a higher expected max.
The native arm carries ~28 configs per SS cell per run and ~143 accumulated;
ZZ's spoof arm carries 26. Re-grading the *same* data under every basis:

| basis | meaning | verdicts (38 cells now visible) |
|---|---|---|
| `winner` (report) | native best-kernel vs spoof best-kernel | **29 W / 9 T / 0 L** |
| `median` | typical native vs typical spoof | 5 L / 3 T / 22 W |
| `floor_best` | typical native vs spoof's BEST | 25 L / 3 T / 2 W |
| `strict` | native worst vs spoof best | 30 L |

**The five `median` losses are the work list.** `CC:256 −63.6 %`,
`SS:512 −46.4 %`, `DD:256 −44.6 %`, `SS:256 −17.6 %`, `HH:256 −4.3 %`. The first
three are cells where the *winner* is genuinely good (native wins them outright
on `winner`) but the surrounding 640+ accumulated kernels drag the median to
18–41 % of the winner. That is an allocation problem, not a tuning problem.

### 11.2 What changed since the last run

1. **The eight HPA contract cells are now visible to the mutator.**
   `ab_records.phase_records` keyed cells without the family dimension, so
   `HH_HPA`/`HS_HPA` kernels (typecode `HHS`/`HSS` → family `HH`) folded into the
   plain HH cells and `_pair_cells` graded **30 of 38** cells. The DB mutator was
   structurally blind to them. Fixed; now **38 cells, 29 W / 9 T / 0 L**, and
   `HH_HPA:512` reads **+118.6 %** — a 2.2× win the arm was never allowed to see.
   Every pre-fix HH-family median is contaminated and must be re-read.
2. **`FORWARD_KNOB_DOMAINS` is family-aware** (`forward_domain(family, knob)`).
   GLVW is now `S:(1,2,4)`, `H:(1,2,4,8)`, `D/C:(1,2)`, `Z:(1,)` against the
   verified 16-B global-load cap — previously every DD/CC/ZZ GLVW≥2 draw was a
   guaranteed gate refusal wasting one of five forward draws per iteration.
   `WorkGroupMapping` is `(1,2,3,4,−1,−4)` (8 is a 56-CU artefact; the negative
   I/J-swap family has never been generated). `StaggerUStride` is
   `(0,64,128,256)` because 256 silently rounds to `DepthU*bpe`.
   `AssertFree1ElementMultiple` joins `AssertFree0ElementMultiple`.
3. **The CC:256 steal batch is decked** (§0 R8): 14 candidates, all gate-legal
   through both `validate_config` and `ldspad_feasible` at 16 KB LDS/WG.
4. **Two latent crashes fixed**: `db_patterns` referenced a non-existent
   `FORWARD_KNOB_DOMAINS["GSU"]` (dead branches, now unreachable), and
   `driver.__init__` built the run dir before the registry.

### 11.3 The search strategy (from the SOTA read)

The TEVC 2022 Kernel Tuner study (arXiv:2210.01465, 26 spaces × 9 GPUs × 16
optimisers, GEMM/OpenCL on MI50): at **≤200 evaluations dual annealing wins and
Bayesian SMAC does not even beat random sampling for GEMM**; first-improvement
local search takes over at 200–800. A per-config cost of generate + assemble +
benchmark puts a 10-hour overnight at a few hundred evaluations — the low-budget
regime. So: **analytic pre-filter → hill-climb the surviving frontier → draw
diagonals last**, and no surrogate model. (arXiv 2407.11488: AMD gains ~10×
from autotuning where NVIDIA gains ~2×, and vendor-tuned configs do not
transfer — honour the SS-pads / DD-never-pads asymmetry rather than averaging.)

### 11.4 What to spend the budget on (ranked, payoff per GPU-minute)

| # | lever | cells | mechanism |
|---|---|---|---|
| 1 | `LdsPadA/B ∈ {1,2,4}` on **CC, ZZ, DD** winner geometries | CC:256, ZZ all, DD:256 | GCN LDS = 32 banks × 4 B, `bank = (addr/4) mod 32`, wave64 serviced in 8 phases of 8 lanes. The floor pads SS (110/162/55 kernels) and HH (17) but **never pads DD/CC/ZZ**, and Tensile's own `Perf/*.yaml` never enumerates pads either — a self-consistent blind spot in both the library and the recipes. |
| 2 | `AssertFree0/1ElementMultiple` = 4 (2 double, 8 half) | all | Tensile's own recipe value. Unlocks `UseSgprForGRO` — the 1-vs-2 WG/CU step on a 256-VGPR part. **Assertion: gate on exact shape divisibility and verify the first row against a reference GEMM.** |
| 3 | MacroTile shrink + `LocalSplitU` | SS:256/512, DD:256, HH:256 | 7-CU cliff: `SS 128x128x8`→4 WG/CU, `128x128x16`→2, `128x128x32`→1; `DD 128x128x16`→**1 WG/CU**. At 256³ a 128×128 tile is 4 workgroups on 7 CUs. LSU fills waves without paying the arithmetic-intensity cost of shrinking the tile. |
| 4 | `WorkGroupMapping ∈ {1,2,3,4,−1,−4}` | CC, HH_HPA, SS small | negative family never generated; 8 is a 56-CU artefact. |
| 5 | `FractionalLoad ∈ {0,1,2}`, `PGR ∈ {0,1,2}`, `PLR 0/1` | SS, CC at 2048 | the floor never emits `FractionalLoad=2` or `PGR=2`. |
| 6 | `NonTemporalA/B ∈ {0,4,8}` | SS/HH 2048+ | avoids L2 (1 MiB) pollution; floor ships 0 everywhere. |

**Do not search** `MatrixInstruction` or `DirectToLds*`: Tensile's `AsmCaps.py`
sets `HasMFMA: False` / `HasWMMA: False` for ISA (9,0,6), so
`SolutionStructs.py:3131-3134` rejects `EnableMatrixInstruction` outright, and
`DirectToLds` blocks `NLCA>1`, forces `GLVW=1` on 8/16-byte dtypes and forces
`1LDSBuffer`. Dead ends that cost search budget.

### 11.5 Deck flood — bound the population before the run

The measured distribution (both arms, folded DB):

| cell | native kernels | within 5 % of winner | median/winner |
|---|---|---|---|
| SS:256 | 684 | 4 | 18 % |
| SS:512 | 693 | 2 | 30 % |
| HH:512 | 742 | 1 | 19 % |
| CC:256 | 246 | 1 | 24 % |
| ZZ:128 | 218 | 1 | 26 % |
| SS:2048 | 668 | 10 | 58 % |

A cell whose median is a fifth of its own winner is a cell in which almost
everything measured was junk. Capping distinct configs per cell at K:

| K | configs retained | share of corpus |
|---|---|---|
| 16 | 523 | 14 % |
| 24 | 765 | 20 % |
| 32 | 1005 | 26 % |

Recommend **K = 24** for the overnight: measured over the folded DB, that
retains **765 of 3831 configs (20 %)** and **loses 0 of 35 cell winners**
(the cap is ranked by measured median, so every cell's frontier survives). `--max-fp N` on
`generate_candidates` is the round-robin knob; the run loop never applies it.

### 11.6 The command

```bash
# 1. CPU-only, from any session (safe under GNOME)
python3 check_candidates.py --family CC --quiet        # legal, or it names the rows
python3 -m oto.harness.generate_candidates --dry-run  # prints the per-family tally
PYTHONPATH=. python3 oto/runners/cli.py --preflight   # 38/38 parity, all OK

# 2. TTY only — the real run
python3 port_tensile.py --auto --budget 10 --yes
```

Sizing: `phases.yaml` plus the seed overlay is what a run builds;
`python3 check_candidates.py --quiet` prints the live deck count and refuses
anything illegal. The last run took 13 h 14 m wall clock for 7.95 h of phase-busy
time (40 % overhead: config generation, Tensile build, queueing), so **~12–14 h**
is the honest estimate and `--budget 10` iterations of mutation on top. Judge
**within-run only**, ≥3 seeds, median, ±2 % tie band.

### 11.7 Read the results honestly

```bash
python3 -m oto.harness.kernel_db --rebuild
python3 allruns.py --json /tmp/opencode/post.json      # knob census + cells_resolved
PYTHONPATH=. python3 oto/runners/cli.py --native-agg floor_best   # the strict basis
```

Report `agg="floor_best"` as a **co-primary** alongside `winner`: it grades the
native arm on its median, so a cherry-picked lucky kernel cannot win it.
`ab_audit.audit`'s max-raw-sample basis should be dropped — `ab_delta._stat`'s
own docstring calls `best` "seed-noisy, reference only".
