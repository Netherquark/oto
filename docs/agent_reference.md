# Agentic Kernel-Tuning Harness Reference

One-page card for agents working on the oto kernel-tuning project.
All checks are **CPU-only** (GNOME session, no GPU benchmarking).
Real benchmarking happens in the user's TTY only.

## Quick Start

```bash
# 1. Is the environment healthy?
python3 -m oto.tools.deck_review score
python3 -m oto.tools.deck_review legality
python3 -m oto.tools.deck_review flood --cap 24

# 2. CPU-only pre-flight
python3 check_candidates.py --quiet
python3 -m oto.harness.generate_candidates --dry-run
PYTHONPATH=. python3 oto/runners/cli.py --preflight

# 3. Pyflakes safety net (fast, CPU-only)
python3 -m pytest tests/test_pyflakes.py tests/test_function_length.py -q

# 4. Full test suite
python3 -m pytest -q

# 5. Gate calibration / failure triage (CPU-only, read-only)
python3 -m oto.harness.gate_calibration --population ours
python3 -m oto.harness.failure_triage
```

## Key Files

| File | Purpose |
|---|---|
| `potential_configs.md` | Master analysis: verdicts, routes, deck |
| `gfx90c_tuning_guide.md` §1.1–§1.2, §9.1 | Primary-source knob reference + geometry |
| `tensile_tuning_context.md` | Stage 0–3 search order + NOT VERIFIED note |
| (research corpus: deleted — durable facts promoted to this doc + gfx90c_tuning_guide.md + tensile_tuning_context.md) | absorbed |
| `oto/device/peaks.py` | Hardware peaks + canonical vocabulary |
| `oto/tensile/decks.py` | FAMILY_DECKS, KNOB_SWEEPS, PLAN_BATCH |
| `oto/tensile/gates/occupancy.py` | LDS + VGPR occupancy gate |
| `oto/tensile/gates/loads.py` | Classic-path global-load divisibility + 16B cap |
| `oto/tensile/gates/assembly.py` | Assembly-class gate (MFMA rejection is here) |
| `oto/tools/deck_review.py` | The three pre-deck questions; its legality census draws the device-truth domain |
| `oto/harness/kernel_db.py` | kernel_db.json builder |
| `oto/harness/gate_calibration.py` | Gate-vs-corpus agreement census: false rejections (gate too strict) and misses (gate too loose) |
| `oto/harness/failure_triage.py` | Empty-phase reason census: why a phase produced no measurement |
| `oto/harness/resolve_cells.py` | Per-cell native+floor winner resolver + the `cfg_gap` tie class |
| `oto/harness/candidate_rows.py` | The candidate deck (`PLAN_BATCH`) and the emitted-overlay rows |
| `oto/tensile/config_writer.py` | The launch boundary: `FORWARDED_KNOBS` / `NOT_FORWARDED_KNOBS` |
| `tests/test_pyflakes.py` | Pyflakes safety-net guard |
| `tests/test_element_assertions.py` | AssertFree* dimension guard |
| `tests/test_db_mutator.py` | GlobalSplitU ban guard |
| `tests/test_deck_review.py` | Deck-review scores counter guard |
| `tests/test_function_length.py` | AC 1b (functions ≤ 60 lines) |

## Hardware — gfx90c (reads from `gfx90c_tuning_guide.md` §0–§1.2)

- 7 CUs / 28 SIMDs / 448 FP32 lanes / Wave64 / 1800 MHz
- LDS 64 KiB/CU (2 WG budget at 32 KiB/WG)
- L2 1 MiB / DDR4 UMA ~42 GB/s → 38 F/B machine balance at SS peak
- **No MFMA** (ISA 9,0,12): MatrixInstruction rejected outright
- 16 B global-load cap (GLVW × bpe ≤ 16)
- Max VGPR 256/thread → accumulator budget is binding

## Pattern: what wins

1. **ThreadTile area scales inversely with bytes-per-element**: HH 8×8, SS 8×8 (111 VGPR),
   DD/CC 4×4, ZZ 2×2. Each sits at the largest TT satisfying `TT_area × bpe ≤ ~64`
   accumulator VGPRs.
2. **LDS at the winner is always 16–25 KB**, never 64 KB (2–4 resident workgroups).
3. **WGM is 4 or 8 at every winner**, never 1 (keeps neighbouring CUs on the same B slice).
4. **The floor never pads CC/DD/ZZ** — the highest-yield untested axis.
5. **The floor never uses** FractionalLoad=2, PGR=2, LdsPad, StaggerU. (It also
   never uses `WaveSeparateGlobalRead` / `1LDSBuffer` / `TransposeLDS` — but those
   are *unreachable*, not merely unmeasured: the launch boundary does not forward
   them, so a candidate naming one benchmarks at the default. See R16.)
6. **Empty on cc/zz**: no LdsPad; on then on for ss/hh — structural blind spot.

## Verdict bases (per `oto/metrics/ab_delta.py`)

| basis | meaning | interpretation |
|---|---|---|
| `winner` | native best-kernel vs spoof best-kernel | drop-in question |
| `median` | typical native vs typical spoof | median-of-seeds basis |
| `floor_best` | typical native vs spoof's BEST | **co-primary, cherry-pick-proof** |
| `strict` | native worst vs spoof best | literal "every way" dominance |

Report `floor_best` as co-primary alongside `winner`.

## Route status (from `potential_configs.md` §8–§9)

| route | status | cells |
|---|---|---|
| A: spoof-steal (CC:256) | decked, 52 rows in PLAN_BATCH | CC:256 |
| B: 14 never-varied knobs | decked in KNOB_SWEEPS | all families |
| C: wave-quantisation ladder | legal only for SS/DD | SS, DD small shapes |
| D: LDS-capacity ladder for Z | pending | ZZ all |
| E: split-complex (3 real GEMMs) | separate work item | CC, ZZ |
| F: persistent fixed grid | conceptual only | all |

## Reading the deck's stragglers

`python3 -m oto.harness.resolve_cells` prints one row per cell with a `cfg_gap`
class; `potential_configs.md` §R17 reads it into a route:

| `cfg_gap` | meaning | lever |
|---|---|---|
| `identical` | native ties on the floor's own tile | co-vary a *forwarded* knob at that tile |
| `near` | same tile, a VectorWidth/DepthU step apart | the width/depth step |
| `retile` | native ties on a *different*, smaller tile | a tile probe, not a width probe |
| `no-floor` | the family ships no floor arm (HPA) | nothing — native is already above the ceiling |

## Do not search

- `MatrixInstruction` / `DirectToLds` — rejected or actively harmful
- `ThreadTile` width ladders for C/Z — accumulator cap makes every wider tile illegal
- `LdsPad`/LDS-layout work on bandwidth-oversupplied families
- `-mllvm -amdgpu-*` compiler flags (no-op: ~93% of shipped library is ISA text)
- `AggressivePerfMode=2` — measured dead: 0 `.hsaco` for every family and every
  tile across two runs, while its mode-1 control built 20. It cost phases, not
  evidence. See `potential_configs.md` §R23.
- `MaxOccupancy` assumptions without measurement
- `WaveSeparateGlobalReadA/B`, `ThreadSeparateGlobalReadA/B`, `1LDSBuffer`,
  `TransposeLDS`, `UnrollMajorLDSA/B`, `LdsBlockSizePerPadA/B`, `DirectToVgprA/B`
  — **not forwarded** by the launch boundary (`config_writer.NOT_FORWARDED_KNOBS`),
  so decking one benchmarks at the default until R20 funds both the forwarding and
  its gate. The harness now strips and *reports* these instead of no-op'ing silently.

## CPU-only contract (`claude.md` §5)

- **Never stress the GPU** from a GNOME session (no sustained `./benchmark` runs)
- `check_candidates.py`, `generate_candidates --dry-run`, and `--preflight` are safe
- Real benchmarking happens in the user's TTY only
- CPU-only legality proofs: `validate_config`, `ldspad_feasible`, `occupancy_feasible`

## The 10h+ overnight run command

```bash
# CPU-only (any session)
python3 check_candidates.py --quiet
python3 -m oto.harness.generate_candidates --dry-run
PYTHONPATH=. python3 oto/runners/cli.py --preflight

# TTY only — the real run
python3 port_tensile.py --auto --budget 10 --yes
```

Sizing: `check_candidates.py --quiet` prints the `phases.yaml` count and
`generate_candidates --dry-run` prints `TOTAL candidates=…`; the run's phase count
is their sum — read those two lines rather than trusting a literal pinned here
(`claude.md`: "Never write a corpus count down — anywhere"). At the current
deck that is ~12–14 h wall clock.
Judge **within-run only**, ≥3 seeds, median, ±2% tie band.

## Post-run read guide

```bash
python3 -m oto.harness.kernel_db --rebuild
python3 -m oto.harness.resolve_cells            # per-cell winners + cfg_gap
python3 allruns.py --json gfx90c_results/analysis/post.json
PYTHONPATH=. python3 oto/runners/cli.py --native-agg floor_best
```

Report `floor_best` as co-primary alongside `winner`. Look for `LdsPad` win on
CC/ZZ/DD (bank-conflict lever) and `FractionalLoad=2` on ragged shapes.