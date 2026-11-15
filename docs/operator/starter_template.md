# <codename> starter — machine briefing for any tuning agent
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d

# Pair: docs/<codename>_starter.md + docs/<codename>_starter.json
# The JSON half is the profile oto loads; this file is the context an agent
# (human or AI) gets BEFORE hunting for facts. See docs/operator/starter_pair.md.

codename: <codename>

## Device identity

<!-- One paragraph: what the device is. Vendor, marketing name, product line
     (e.g. Ryzen AI laptop APU / Radeon APU / Radeon PRO / Instinct),
     APU-vs-dGPU-vs-datacenter, memory subsystem (shared DDR / HBM / GDDR),
     form factor and known SKU range targeted. -->

## Why we're tuning for it

<!-- The goal of THIS tuning run. Typical shapes: build a best-effort Tensile
     library for the SKU (Class B), calibrate the CPU legality gates for the
     device, prove a candidate deck on the acceptance bar, or verify the floor
     replica. State success: e.g. "library builds + loads", or "floor parity",
     or "correctness verdicts for the N trial rows". -->

## The apparatus you have to drive

One paragraph per piece, each pointing at its home doc — read all of them
before touching anything:

- `docs/operator/starter_pair.md` — the pair protocol and who verifies what.
- `docs/operator/operator_runbook.md` — the end-to-end Class B contract (detect →
  starter → research → human gate → generate → harness study → TTY run →
  `--best-library`). Read it even if you are only doing docs.
- `docs/developer/harness_runbook.md` — the **working mineral**: what a completed
  gfx90c-style tuning reference library looks like (ceilings, knob domains,
  geometry, M1-M4 mechanisms, failure classes). Aim to reproduce this shape of
  depth for <codename>, not to outdo it.
- `docs/cli.md` — the `oto` command vocabulary (`oto doctor`, `oto check`,
  `oto agent generate`, `oto agent index`).
- `docs/operator/gfx902_starter.md` — a filled-in example of THIS file, for a device
  that does not exist yet anywhere except in agent research. Copy its
  structure; fill in *your* device.
- `docs/gfx90c/gfx90c_theoretical_limits.md` + `docs/gfx90c/gfx90c_tuning_guide.md` — the worked
  example of a completed acceptance document and its cookbook sibling. Read
  the structure, not the numbers — your numbers come from the research
  hunt below.

## What facts you must hunt for (all of them, first-party only)

Group every fact with its source below; an item with no first-party source
is UNVERIFIED and goes in the `## Research (UNVERIFIED ...)` section, never
in the `.json` half:

1. **ISA**: exact LLVM target string (e.g. `amdgpu-gfx90c`), ISA version
   triple, all instructions the device adds/drops vs the nearest sibling
   (gfx906/gfx90a/gfx1103 for APUs — no MFMA, no packed BF16, GSU legality
   differences for complex). Source: AMD ISA reference manual PDF for the
   arch; `llvm-amdgpu docs`; `rocminfo` on a known machine.
2. **CUs, SIMDs, lanes, waves**: CU count for the SKU, SIMDs per CU, lanes
   per SIMD, max waves per CU. Source: AMD product brief / Processor Product
   Catalog (Ark); `rocminfo`.
3. **Clocks**: base, boost, sustained/realistic (sustained matters for bars,
   not boost). Source: AMD SKU spec; `rocm-smi`.
4. **LDS per CU and VGPR modes**: LDS bytes per CU, whether the device reads
   32 KB or 64 KB per CU, per-workgroup legality envelope. Source:
   architecture manual + `rocminfo` LDS fields; the gate in
   `oto/tensile/gates/occupancy.py` does the math — do NOT copy gfx90c's
   16384 B constant; it is a calibrated gfx90c decision.
5. **Memory subsystem**: HBM vs GDDR vs shared DDR; bandwidth GB/s
   (derived from memory config, channel count, TTY); ECC; LLC size. Source:
   SKU spec; `rocm-smi --showmem`.
6. **Compute peaks** per precision: FP32, FP16, packed BF16, INT8, FP64
   (and FP16-dual-issue if applicable). Compute from clock × CUs × lanes ×
   IPC — show the arithmetic; show your sources.
7. **Realistic ceilings** — not "peak × 0.75". Derived from the FP32/FMA-
   bound roofline with measured overheads (memory, sync, epilogue), or
   taken from a measured corpus and justified. Cite the derivation.
8. **Family shapes per dtype** (SS/DD/HH/CC/ZZ/HH_HPA/HS_HPA): the cube
   sides this device realistically ships Tensile kernels for (e.g.
   256/512/1024/2048/4096), driven by CUs and resident waves; see the
   gfx90c profile for the shape.
9. **SKU-vs-codename provenance**: which LLVM target `rocminfo` reports
   (gfx902) vs the marketing name (e.g. "Radeon 680M") — record both.

## Research brief (for agent-1 / agent-2)

Specific questions the agent research must answer before the human gate
signs off — copy this list into your run:

- LLVM target & ISA triple; ISA additions/removals vs siblings; is
  GlobalSplitU legal on this device for complex (no-MFMA) families?
- CU count, SIMD layout, lane width, max waves — for the exact SKU.
- Peak and realistic clocks; peak FP32; FP64 rate (1/16 for APUs).
- LDS per CU; LDS budget policy suggestion (with derivation, flagged as
  a hypothesis for TTY verification).
- Best-effort realistic ceilings per family/dtype — article-level sources.
- Which Tensile commit is pinned (`TENSILE_ROOT`), and whether it
  understands this arch — the arch may not exist in Tensile; verify with
  `Tensile --version` and ISA-table lookup.
- The LLVM manual section for this subarch family (prokaryote/APU variants).

## Outputs (what the agent writes)

- `docs/<codename>_theoretical_limits.md` — agent-1 output: clocks, peaks,
  roofline, ceilings, acceptance bars, hardware section.
- `docs/<codename>_tuning_context.md` — agent-2 output: knob surface, family
  shapes, what to build.
- `docs/<codename>_harness_study.md` — from `oto/agents/agent_tools.py`:
  corpus census + gap analysis seeded for this device.
- Eventually `profiles/<codename>.json` — after the human verifies every
  number against a first-party source. NEVER before.

All agent output is tagged UNVERIFIED until checked. An unverified number in
a profile is a bug, not a feature.

## Hard rules

1. GPU work only in the TTY — never run Tensile/GPU work from a GUI session
   or background agent. Matrix size cap for in-repo experiments ≤ 512² unless
   the TTY session owner sets otherwise.
2. All runs validate against Tensile's own `NumElementsToValidate` reference;
   the shipped `config_writer.py` sets 128. Never turn it back to 0.
3. No GPU claim without a ledgered row and a run directory; no perf claim
   without a paired native-vs-floor arm and a common timer.
4. Every candidate must pass the CPU gates first (`oto check candidates`,
   `ldspad_feasible`, `validate_config`); a GPU run for an illegal config is
   wasted budget — this is the lesson of the D2/D3/RR legality gates.
5. Do not move the gfx90c bars, ceilings, or gates for this device — the
   device has its own JSON; the repo keeps gfx90c facts in `profiles/`.

## API key

<!-- Name the env var, never the key. The research backend is chosen at run
     time from the environment (see docs/operator/starter_pair.md); nothing about the
     key reaches this file. -->

```
export ANTHROPIC_API_KEY=...   # or: OPENAI_API_KEY / OTO_API_KEY
```

## Worked example

`docs/operator/gfx902_starter.md` — a filled-in instance of this brief for a device
that exists only in agent research. Read it before writing yours; copy its
section discipline, not its numbers.
