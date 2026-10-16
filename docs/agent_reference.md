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
```

## Key Files

| File | Purpose |
|---|---|
| `potential_configs.md` | Master analysis: verdicts, routes, deck |
| `gfx90c_tuning_guide.md` §1.1–§1.2, §9.1 | Primary-source knob reference + geometry |
| `tensile_tuning_context.md` | Stage 0–3 search order + NOT VERIFIED note |
| `archive/corpus4.tuning_20261016.md` | Raw research corpus (read-only) |
| `oto/device/peaks.py` | Hardware peaks + canonical vocabulary |
| `oto/tensile/decks.py` | FAMILY_DECKS, KNOB_SWEEPS, PLAN_BATCH |
| `oto/tensile/gates/occupancy.py` | LDS + VGPR occupancy gate |
| `oto/tensile/gates/loads.py` | Classic-path global-load divisibility + 16B cap |
| `oto/tensile/gates/assembly.py` | Assembly-class gate (MFMA rejection is here) |
| `oto/tools/deck_review.py` | The three pre-deck questions |
| `oto/harness/kernel_db.py` | kernel_db.json builder |
| `oto/harness/resolve_cells.py` | Per-cell native+floor winner resolver |
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
5. **The floor never uses** FractionalLoad=2, PGR=2, WaveSeparateGlobalRead, 1LDSBuffer, etc.
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
| B: 14 never-varied knobs | decked, 12 in KNOB_SWEEPS | all families |
| C: wave-quantisation ladder | legal only for SS/DD | SS, DD small shapes |
| D: LDS-capacity ladder for Z | pending | ZZ all |
| E: split-complex (3 real GEMMs) | separate work item | CC, ZZ |
| F: persistent fixed grid | conceptual only | all |

## Do not search

- `MatrixInstruction` / `DirectToLds` — rejected or actively harmful
- `ThreadTile` width ladders for C/Z — accumulator cap makes every wider tile illegal
- `LdsPad`/LDS-layout work on bandwidth-oversupplied families
- `-mllvm -amdgpu-*` compiler flags (no-op: ~93% of shipped library is ISA text)
- `MaxOccupancy`/`AggressivePerfMode` without measurement

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

Sizing: 308 deck phases + 372 seed rows ≈ 680 phases, ~12–14 h wall clock.
Judge **within-run only**, ≥3 seeds, median, ±2% tie band.

## Post-run read guide

```bash
python3 -m oto.harness.kernel_db --rebuild
python3 allruns.py --json /tmp/opencode/post.json
PYTHONPATH=. python3 oto/runners/cli.py --native-agg floor_best
```

Report `floor_best` as co-primary alongside `winner`. Look for `LdsPad` win on
CC/ZZ/DD (bank-conflict lever) and `FractionalLoad=2` on ragged shapes.