# Agentic Kernel-Tuning Harness Reference

One-page card for agents working on the oto kernel-tuning project.
All checks are **CPU-only** (GNOME session, no GPU benchmarking).
Real benchmarking happens in the user's TTY only.

## Quick Start

```bash
# 0. What has the corpus already measured here?
python3 -m oto.harness.corpus_census --cell SS:1024
python3 -m oto.harness.corpus_census --family SS --knob DepthU

# 1. Is the environment healthy?
python3 -m oto.tools.deck_review score
python3 -m oto.tools.deck_review legality
python3 -m oto.tools.deck_review flood --cap 24

# 2. CPU-only pre-flight
python3 oto.py check candidates --quiet
python3 -m oto.harness.generate_candidates --dry-run
python3 oto.py doctor

# 3. Pyflakes + ruff + py_compile + length safety nets (fast, CPU-only)
python3 -m pytest tests/test_pyflakes.py tests/test_ruff.py tests/test_py_compile.py tests/test_function_length.py tests/test_file_length.py -q
OTO_GUARD_FILES=1 python3 -m pytest tests/test_pyflakes.py tests/test_ruff.py tests/test_py_compile.py tests/test_function_length.py tests/test_file_length.py -q  # changed files only

# 4. Full test suite (2m10s serial, 1m27s with -n auto)
python3 -m pytest -q
python3 -m pytest -q -n auto          # distributed (pytest-xdist)
python3 -m pytest -q -m preflight      # the pre-run subset the checklist runs (37 s)

# 5. Gate calibration / failure triage (CPU-only, read-only)
python3 -m oto.harness.gate_calibration --population ours
python3 -m oto.harness.failure_triage
python3 -m oto.harness.rule_calibration               # probe proposed rules
```

## Key Files

| File | Purpose |
|---|---|
| `potential_configs.md` | Master analysis: verdicts, routes, deck |
| `gfx90c_tuning_guide.md` §1.1–§1.2, §9.1 | Primary-source knob reference + geometry |
| `tensile_tuning_context.md` | Stage 0–3 search order + NOT VERIFIED note |
| (research corpus: deleted — durable facts promoted to this doc + gfx90c_tuning_guide.md + tensile_tuning_context.md) | absorbed |
| `oto/device/peaks.py` | Hardware peaks + canonical vocabulary |
| `oto/yamlio.py` | The project's YAML reader: libyaml when present, memoised by content |
| `oto/tensile/gates/memo.py` | The content-keyed memo the pure legality gates use |
| `oto/tensile/decks.py` | FAMILY_DECKS, KNOB_SWEEPS, PLAN_BATCH |
| `oto/tensile/gates/occupancy.py` | LDS + VGPR occupancy gate |
| `oto/tensile/gates/loads.py` | Classic-path global-load divisibility + 16B cap |
| `oto/tensile/gates/assembly.py` | Assembly-class gate (MFMA rejection is here) |
| `oto/tools/deck_review.py` | The three pre-deck questions; its legality census draws the device-truth domain |
| `oto/harness/kernel_db.py` | kernel_db.json builder |
| `oto/harness/corpus_census.py` | Corpus history: axis/geometry coverage and per-cell geometry history, from kernel_db |
| `oto/harness/gate_calibration.py` | Gate-vs-corpus agreement census: false rejections (gate too strict) and misses (gate too loose) |
| `oto/harness/rule_calibration.py` | Probe a proposed gate rule in isolation: false rejections (must be 0) + empty-phase catches, by family |
| `oto/harness/failure_triage.py` | Empty-phase reason census: why a phase produced no measurement |
| `oto/harness/resolve_cells.py` | Per-cell native+floor winner resolver + the `cfg_gap` tie class |
| `oto/harness/coverage_map.py` | The legal geometry space per cell, what the corpus measured in it, and the unmeasured geometries ranked by their neighbours' score |
| `oto/harness/tensile_oracle.py` | The legality oracle: Tensile's own verdict on a config, the LDS it allocated, and our gate's verdict beside it |
| `oto/harness/deck_check.py` | The pre-run sweep: every *unmeasured* deck row through Tensile's kernel writer, resumable, CPU-only |
| `oto/harness/coverage_graph.py` | The coverage graphs: the legal geometry space per cell as a 2D picture, with the unexplored part hatched, the peaks ringed green and the traps ringed red |
| `oto/metrics/report_figures.py` | The acceptance report's problem-space coverage section (the figures + their numbers) |
| `oto/tensile/patterns.py` | The contraction-pattern vocabulary: one spelling, one meaning (the transpose flags and the TLU layout flags) |
| `oto/harness/candidate_rows.py` | The candidate deck (`PLAN_BATCH`) and the emitted-overlay rows |
| `oto/tensile/config_writer.py` | The launch boundary: `FORWARDED_KNOBS` / `NOT_FORWARDED_KNOBS` |
| `tests/conftest.py` | The `serial` / `preflight` markers, the serial rule, the corpus fixtures |
| `tests/test_pyflakes.py` | Pyflakes safety-net guard |
| `tests/test_ruff.py` | Ruff safety-net guard (pinned rule set in `ruff.toml`) |
| `tests/test_py_compile.py` | Every tracked `.py` must byte-compile |
| `tests/test_file_length.py` | No tracked `.py` over 600 lines (grandfathered list ratchets down) |
| `tests/test_element_assertions.py` | AssertFree* dimension guard |
| `tests/test_tile_frontier.py` | The legal MacroTile frontier above 16384 elements |
| `tests/test_corpus_census.py` | Corpus-history census: median basis, geometry collapse, per-cell history |
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
7. **MacroTile area above 16384 is legal only for 256×128 / 128×256** (VW2, or
   VW4 under `AssertFree1ElementMultiple`), plus 64×512 / 512×64 at DU8 for the
   16-bit-input families. CC, DD and ZZ admit **no** legal tile above 16384 at
   all, so their ORANGE cells are a bar artifact — `gfx90c_theoretical_limits.md`
   §5.1, deck in `candidate_rows._FRONTIER`.

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

`python3 -m oto.harness.coverage_graph` draws the corpus's coverage of the
problem space: one SVG per contract cell (plus an index page) with the legal
geometry space projected onto (macro-tile area x accumulators per thread), the
measured part painted with the value it reached, the legal-but-unmeasured part
hatched, and the local maxima (peaks) and local minima (traps) ringed. The
headline it carries: **86-93 % of the legal geometry space has never been
measured** in every cell but ZZ, and the traps sit *inside* the measured strip
-- the search keeps falling back on a configuration whose neighbours are
3-8x faster.

`python3 -m oto.harness.tensile_oracle --dtype Z --macro 64x64x8 --thread 2x2
--vw 1 --du 8` asks **Tensile itself** whether a config builds, what LDS it
allocated and what our gate said -- the way to settle a legality question the
CPU gates cannot answer (it is what found the load-divisibility bug: the gate
modelled `totalVectorsCoalesced` as the coalesced part alone, so its NLCA check
was against the wrong number).

`python3 -m oto.harness.coverage_map --cell SS:256` answers the question the
census cannot: not "what has been measured" but "what *could* have been" -- the
legal geometry space per cell, the part of it the corpus covers (8-13 %), and
the legal-but-unmeasured geometries ranked by how well their neighbours
measured. That is the local-minimum finder: the neighbourhood is fast and the
point itself is untried.

`python3 -m oto.harness.resolve_cells --taxonomy` says what each verdict is
made of: on the `identical` cells both arms run the *same* config, so their
delta is measurement environment, and the spread over those cells (17.5
points) is the band any real win has to clear.

`python3 -m oto.harness.resolve_cells` prints one row per cell with a `cfg_gap`
class; `potential_configs.md` §R17 reads it into a route:

| `cfg_gap` | meaning | lever |
|---|---|---|
| `identical` | native ties on the floor's own tile | co-vary a *forwarded* knob at that tile |
| `near` | same tile, a VectorWidth/DepthU step apart | the width/depth step |
| `retile` | native ties on a *different*, smaller tile | a tile probe, not a width probe |
| `no-floor` | the family ships no floor arm (HPA) | nothing — native is already above the ceiling |

Before proposing the probe, read the cell's full history:
`python3 -m oto.harness.corpus_census --cell FAM:side` lists every geometry the
corpus has measured on that cell, the row count behind each, and the floor's
best — so a `retile` route cannot re-propose a geometry that already lost, and
`potential_configs.md` §R41's closed axes stay closed.

## Do not search

- `MatrixInstruction` / `DirectToLds` — rejected or actively harmful
- `ThreadTile` width ladders for C/Z — the per-thread accumulator cap (`TT0*TT1*R
  > 128`) makes every wider thread tile illegal
- **Wider MacroTile for C/Z** — provably closed (`potential_configs.md` §R27):
  the workgroup register-file rule (`R*MT0*MT1*LSU < 65536`) caps area at
  `65536/R`, so the widest legal complex tiles are CC `128x64` and ZZ
  `64x64`/`128x32`; a brute force above those areas finds none legal
- `LdsPad`/LDS-layout work on bandwidth-oversupplied families
- `-mllvm -amdgpu-*` compiler flags (no-op: ~93% of shipped library is ISA text)
- `AggressivePerfMode=2` — now **refused at the generator seam**
  (`candidate._non_generative_knob_rejection`): the assembly path cannot emit it
  (`Components/Priority.py` dispatches only 0/1, so `MAC_F32C` raises
  `TypeError`). 0/28 built across every family. The writer still forwards it by
  contract. See `potential_configs.md` §R24.
- `MaxOccupancy` assumptions without measurement
- `WaveSeparateGlobalReadA/B`, `ThreadSeparateGlobalReadA/B`, `1LDSBuffer`,
  `TransposeLDS`, `UnrollMajorLDSA/B`, `LdsBlockSizePerPadA/B`, `DirectToVgprA/B`
  — **not forwarded** by the launch boundary (`config_writer.NOT_FORWARDED_KNOBS`),
  so decking one benchmarks at the default until R20 funds both the forwarding and
  its gate. The harness now strips and *reports* these instead of no-op'ing silently.

## CPU-only contract (`claude.md` §5)

- **Never stress the GPU** from a GNOME session (no sustained `./benchmark` runs)
- `oto check candidates`, `generate_candidates --dry-run`, and `oto doctor` are safe
- Real benchmarking happens in the user's TTY only
- CPU-only legality proofs: `validate_config`, `ldspad_feasible`, `occupancy_feasible`
- **Any `pytest` invocation during programming takes minutes and must be run in
  the background** (background mode) so the conversation is not blocked; read the
  result when it completes. Never sleep/poll for it.
- **The suite is fast now** (2 m 10 s serial, 1 m 27 s with `-n auto`,
  37 s for `-m preflight`): the YAML reader uses libyaml, the corpus reads are
  memoised and the legality gates are cached by config content. A run that
  takes longer than that is doing something new -- check the durations
  (`pytest --durations=10`) before assuming the machine is slow.

## The overnight run command

```bash
# CPU-only (any session)
python3 -m oto.harness.generate_candidates          # wire the seed overlay
python3 oto.py check candidates --quiet
python3 oto.py check candidates --deck gfx90c_results/overlays/phases.seed.overlay.yaml --quiet
python3 -m oto.harness.generate_candidates --dry-run
python3 oto.py doctor

# TTY only — the real run
python3 oto.py tune --budget 10 --yes
```

The overlay is gitignored, so wiring it in is a required step, not a no-op.
The run's phase count is the committed deck plus the overlay rows; read the
overlay count and the dry-run's "would append N" line (0 after a correct wire)
rather than trusting a literal pinned here (`claude.md`: "Never write a corpus
count down — anywhere"). `--budget 10` makes the run exit once the deck is
exhausted.
Judge **within-run only**, ≥3 seeds, median, ±2% tie band.

## Post-run read guide

```bash
python3 -m oto.harness.kernel_db --rebuild
python3 -m oto.harness.resolve_cells            # per-cell winners + cfg_gap
python3 oto.py stats --json gfx90c_results/analysis/post.json
PYTHONPATH=. python3 oto/runners/cli.py --native-agg floor_best
```

Report `floor_best` as co-primary alongside `winner`. Look for `LdsPad` win on
CC/ZZ/DD (bank-conflict lever) and `FractionalLoad=2` on ragged shapes.
## Report regeneration & visual check

After a run completes and the JSON payload is written, regenerate the HTML
dashboard and run the visual check:

```bash
# From repo root; regenerates acceptance_report.html in the run dir
python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, '.')
from oto.metrics.report_models import ABVerdict, AcceptanceReport
from oto.metrics.report import AcceptanceReporter
run = Path('gfx90c_runs/run_...')  # the run ID
payload = json.loads((run / 'acceptance_report.json').read_text())
payload['per_cell_verdicts'] = [ABVerdict(**v) for v in payload.get('per_cell_verdicts', [])]
report = AcceptanceReport(**payload)
AcceptanceReporter(Path('.').resolve()).write_html_report(report, run / 'acceptance_report.html')
PY

# Visual/layout regression check (requires playwright + chromium)
python3 -m oto.harness.visual_check gfx90c_runs/run_.../acceptance_report.html
```

The visual check validates no horizontal overflow, correct table scrolling,
metric grid column counts, and section presence at desktop (1440px) and mobile
(390px) viewports.
