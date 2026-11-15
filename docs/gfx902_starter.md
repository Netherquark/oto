# gfx902 starter — narrative half of the pair
# Pair: docs/gfx902_starter.md + docs/gfx902_starter.json
# Facts live in the .json and in profiles/gfx902.json (once verified).
# See docs/starter_pair.md.

codename: gfx902

## Target

AMD **gfx902** — the iGPU silicon in Raven Ridge / Picasso-class Ryzen
APUs (public GPU tables list GFX902 = RAVEN, GCN 5.0; LLVM's AMDGPU docs
map `amdgpu9.02` to gfx902). We are tuning Tensile-class GEMM kernels for
this device and verifying oto's port on it.

## Why we're tuning for it

Verify the device-independent port end to end on a second, different device:
library build, report generation, gate calibration — all against
`--codename gfx902`.

## Known quirks / open questions (for the agents to research + verify)

- Exact part this machine has: CU count, SIMD layout, clock targets
  (which SKU — 2200G/2400G/3200G/3400G/etc.?).
- ISA triple and xnack mode; any relevant errata vs gfx900/gfx906/gfx90c.
- Base/boost clock and peak FP32 (with the calculation shown).
- Any MFMA or not (expected: none on Vega-class) and DP4A support.
- First-party URLs (AMD ISA reference, ROCm release notes / support matrix).
- Internal 64KB LDS per CU and VGPR budget: confirm vs the GCN 5 family.
- BLAS-8-reported shape set for this APU if one exists.

## Research brief (for the agents)

Produce, with citations:
1. `isa`, `num_cus`, `simds_per_cu`, `lanes_per_simd`, `max_waves_per_cu`,
   `max_clock_mhz`, `lds_per_cu_kb`, `l2_size_kb`, `vgpr_per_cu`.
2. `family_shapes` (SS/DD/HH/CC/ZZ/HH_HPA/HS_HPA) best-supported shapes
   for this APU — or state explicitly that there is no public answer.
3. Peak FP32 GFLOPS with the arithmetic shown; BLAS-8-reported values if
   published anywhere authoritative.
4. Anything about driver/kernel behavior that matters for kernel-gen
   rejects (MFMA/dp4a/bank conflicts).

Mark every number UNVERIFIED until a human checks it against a first-
party source; transcribe to the .json half only after verification.

## API key

Set one of these in the shell on the machine that runs
`oto agent generate` (never commit a key):

    export ANTHROPIC_API_KEY=...     # preferred, agent uses web_search tool
    # or export OPENAI_API_KEY=...   # uses gpt-4o-mini-search-preview
    # or export OTO_API_KEY=pplx-... # Perplexity, model sonar
