# The oto tuning campaign — an unsupported AMD GPU, start to converged

**Class B document.** Read this when you run `oto` on a GPU that upstream
does not ship a Tensile library for — or a spoofed cousin of one. You are the
agent. There is no supervisor; the plan in this file is the supervisor.

`oto` is designed to be run by someone who knows nothing about their hardware
beyond “it’s an AMD GPU”. Everything you need is in this file; every command
it issues either exists in this repo or fails loudly with a reason.

## 1. The contract, in three lines

1. The target is a **working TensileLibrary.dat** for `benchmarked ceiling-
   approaching performance`, built for an unsupported GPU, verified as far
   as honestly possible without inventing hardware facts.
2. `oto` is the operator. You do not hand-tune; you do not second-guess the
   gates; you do not over-rule the acceptance report.
3. You stop when convergence is proven (§9) or blocked (§10). Nothing else
   is a stopping condition.

## 2. What this file covers

The whole arc, start to finish:

```
starter file → oto doctor → agent generate (4 docs) → library best-effort
→ choose the convergence model (§5) → grind to the ceilings (§6)
→ sign-off (§9)
```

Two convergence models, picked per device (§5):

- **Blind** — no floor to beat. Theoretical roofs, derived from the silicon.
- **Informed** — a spoofed floor exists (e.g. gfx90c vs gfx900). Steal configs from the floor for the worst cells, document every tweak, measure before shipping.

## 3. The starter file — the only human interaction

Everything else flows from it. Copy and fill:

```bash
cp docs/starter_template.md   docs/<codename>_starter.md
cp docs/starter_template.json docs/<codename>_starter.json
```

Hardware facts you must fill (from `rocminfo`, `sysfs`, ROCm release docs,
first-party spec sheets):

| field | rule |
|---|---|
| `codename` | from `rocminfo`'s `Name:` line — e.g. `gfx902` |
| `isa` | `gfx_target_version` as `[major, minor, stepping]` — e.g. `(9, 0, 8)` |
| `num_cus` | compute units from `rocminfo` |
| `simds_per_cu`, `lanes_per_simd` | from ISA manual for this class |
| `max_clock_mhz` | spec sheet / `pp_dpm_sclk` |
| `lds_per_cu_kb`, `l2_size_kb`, `vgpr_per_cu` | spec sheet / `gather_device_profile.py` evidence |
| `global_load_byte_cap` | instruction-set cap (usually 16) |
| `has_mfma`, `has_dp4a`, `has_packed_bf16` | from ISA behavior on this part (ISA oracle) |
| `family_shapes` | the cube list to tune; 7 gfx90c families are the default example |
| `spoof_reference` | the floor's codename (e.g. `gfx900`), **or leave empty for blind mode** |

Everything not provided gets **derived**, not invented — see §4. Missing or
zeroed fields still produce a library, but it is a knee-jerk fallback; verify
before shipping.

## 4. The four docs — what gets generated, and what must not be hand-edited

```bash
python3 -m oto agent generate docs/<codename>_starter.md
```
`python3 -m oto agent generate` emits (cold cache: a few minutes,
network optional):

| file | producer | owner (runs every time) |
|---|---|---|
| `<codename>_theoretical_limits.md` | agent-1 | `oto.device.derive` — the formula; the agent writes narrative, not numbers |
| `<codename>_tuning_context.md` | agent-2 | profile + hardware facts; peaks inline |
| `<codename>_harness_study.md` | CPU harness | `oto.harness.corpus_census` + `resolve_cells` outputs |
| `<codename>_potential_configs.md` | agent-1+2 | the synthesis step |

The `# 1. ALU peaks (derived)` section of `<codename>_theoretical_limits.md`
is computed, not copied — it prints the formula and the profile-agrees/  
mismatch pair side by side. `oto.device.derive` is the authority; if it
disagrees with the profile, the profile has a mistake. Fix the profile,

regenerate. Never tune a ceiling by hand.

If no API key is set: the docs still generate, with the research sections
emitted as stubs — the run is not blocked, but records are marked UNVERIFIED
until human review.

## 5. Pick the convergence model

| question | answer | model |
|---|---|---|
| Is there a reference TensileLibrary for your codename (or your ISA family) built for a related but different arch? | yes | **informed** — floor to beat |
| No reference — you are the first to ship it? | yes | **blind** — only this part's contents |
| Can you SEE a reasonable floor by retargeting another arch's library for your part? | yes (rare) | **informed + caveat** — treat floor proof as weak |

### 5.1 Informed convergence (spoof exists, e.g. gfx90c/gfx900)

Library to beat: `gfx900` (or the spoofed GEMM from another arch). The
workflow:

1. `oto agent generate` → docs carry the floor pointer in
   `spoof_reference` — the report compares native vs floor.
2. `python3 -m oto library best-effort` — carve a `.dat` from whatever your
   deck has beaten so far. Cells not yet beaten from the floor are sourced
   from the floor.
3. Tune with the **floor-steal protocol** (the only conservative copy in
   the codebase):
   - Pick the WORST native cells, not the leaders.
   - Take the floor winner for that cell.
   - Keep the floor kernel's full config, then port to `<this-device>` by
     re-deriving the parts that differ in CU count / L2 / LDS / wave
   - **Document every altered field and why** in the config note (`note`).
   - Gate-test, benchmark — never ship an unmeasured steal.
4. Accept when ≥ 38/38 of the cells beat or tie the floor cell verdict.

Example: the CC:256 cell once read native ≈ 211 vs floor ≈ 215 (−0.74 %).
The steal (`AssertFree0ElementMultiple: 4, AssertFree1ElementMultiple: 4`) was
GPU-validated, gate-legal, and shipped as a first-class deck row at both
256³ and 512³ — adoption was a decision the owner made, not a ceiling such
as “must win”. Steal then A/B — never steal then assume.

### 5.2 Blind convergence (no floor exists)

No floor to beat means the bars are the theoretical roofs for this device —
which are *derived*, not inherited, and deterministic:

1. `oto agent generate` → `*_theoretical_limits.md` carries §1 “ALU peaks
   (derived)”: lanes, FMA rate, table. **These are arithmetic.** Nobody
   set them; nobody can override them. If the hardware cannot reach them,
   that is the truth about the hardware — not about the tuning.
2. From the profile, the 38-cell matrix is the full seat to fill.
3. Propose the full matrix *without a floor*:
   - large-square middle (1024³-class) — sensible tile ladders from
     `TARGET_CELLS` in `oto.harness.candidate_rows` (shared geometry wheel,
     not derived per-arch assumptions),
   - sweep dummy kernels at each shape: `python3 -m oto.harness.generate_candidates --dry-run`,
   - run overnight: `python3 -m oto tune --budget 10 --mutations 3`.
4. Fill the weak cells one at a time using the same apparatus as §5.1 — a
   blind floor is just a *guess shaped like a floor* that gets replaced as
   soon as first measurements exist. Keep the guess small and cheap: a
   plausible tile at the largest cube is all it takes to start measuring.
5. The first blind run is the calibration: enqueue cells, measure,
   learn which knobs matter on *this* silicon, refine the geometry wheel,
   inherit nothing blindly.

Blind acceptance = “as close to the derived roofs as the kernels can be,
measured per family, per cell, with clock coverage in every verdict. No
claim of “converged” without enough cells at the ceiling gates — the same
bar informed mode has, with nothing to steal from.

## 6. The campaign

Once the library exists (`library best-effort`), the real work runs through
the autonomous convergence loop:

```bash
python3 -m oto tune --budget 10 --mutations 3
```
`oto tune` is the convergence loop: it harvests winners from the last batch,
mutates at most two knobs at a time (`NARROW` draws: 1–3 forward-knob deltas;
`WIDE`: floor/DB tile donors × forward draws; `DIRECTION`: move parent
toward the floor winner), gates every mutant, novelty-checks by fingerprint
against the ledger, and benchmarks in the TTY — no human per phase. It stops
at `--budget` plain n iterations.

You supervise cold-start: the first pass harvests nothing, so set sensible
geometry seeds by adding `phases.yaml` entries (see §8) — that is the only
hand-authorable part left.

## 7. The rules you cannot break

1. **GPU only in the TTY.** Every benchmark metric originates from runs in
   a terminal launched by `oto tune` or from the launch/proof commands in this
   file — never from a desktop session, never from an unattended queue. GPU
   probes from a desktop MUST stay ≤ 512² build probes.
2. **CPU gates are not measurement.** A candidate passing `oto check
   candidates` is legal to try, not proven competitive.
3. **Measured only.** Every claims-based drop in performance bars MUST be
   accompanied by a TTY measurement.
4. **Typecode is truth.** Family attribution reads kernel headers only; no
   phase ids, no directory prefixes, no filenames implying anything.
5. **Append-only.** Registry.db, kernel_db.json, reports — never edit. Fresh
   state comes from fresh runs, full stop.
6. **Like-for-like.** Verdicts compare under the same protocol, always. The acceptance report grades one protocol at a time; do not re-implement its logic.
7. **Clock coverage or silence.** A verdict over a run with weak
   `clock_coverage` is a NULL, not a number — re-measure.
8. **No silent skips.** A dropped phase must have a reason written next to it.
9. **Steal documented.** Any foreign config lifted into this deck carries a
   note naming intention (see §5.1).
10. **Walls are walls.** A cell that hits the ceiling after multiple runs
    stops being worked on. Walls live in `incomplete_work.md` with
    `MEASURED` beside them. Do not re-litigate.

## 8. Extending the deck for a run

The deck (`phases.yaml`) is seeded by the generator; you add rows when a
new hypothesis lands:

```bash
python3 -m oto.harness.generate_candidates --dry-run   # sizes the pool
python3 -m oto.harness.generate_candidates             # emits overlay + deck entries
python3 -m oto check candidates                          # 0 illegal or stop
```

`phases.yaml` growth is by `git commit` by the owner (the user) — one commit
per row; never batch-edit.

## 9. Sign-off — what “done” means

A campaign is done when, for the 38 target cells (or the cells your starter
file defined), all hold:

| gate | how to check |
|---|---|
| library builds | `python3 -m oto library best-effort` exits 0; `.dat` loads under PyTorch; a GEMM vs reference on random inputs matches within dtype tolerance |
| `oto.check candidates` passes | 0 illegal on the current deck |
| acceptance report like-for-like | `oto report --json`; verdicts recorded |
| floor/roof | informed: every cell beats or ties floor verdicts; blind: measured % of §1 derived roof printed in the report |
| clocks | every verdict has ≥ e.g. 50 % clock coverage in its run |
| sign-off doc | `incomplete_work.md` lists residual gaps; every one carries a measured reason |

Do not declare convergence from one run; require ≥ 2 (one preload + one
measurement).

## 10. If stuck

| symptom | response |
|---|---|
| `oto doctor` reports a profile failure | fix the profile, not the code — the profile is the data, the code is derived |
| a kernel always fails with error 4 | occupancy gate refusal: shrink tile / increase residency |
| a kernel hits the barrier but the bar says orange | it is at the ceiling (see §7) — walls are not failures; note them and move on |
| `stagnation`: three runs, no cell moves beyond ±2 % | your hypotheses are exhausted — check `incomplete_work.md`, `potential_configs.md` for untouched neighbours/axes; if truly no move, declare measured and escalate |

### Running the command

```bash
python3 -m oto doctor ; python3 -m oto library best-effort ; \
  python3 -m oto tune --budget 10 --mutations 3 ; python3 -m oto report --json
```

Long pages of logs are a feature. The report is the point; the rest is plumbing.
