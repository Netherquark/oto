# <codename> starter — narrative half of the pair
# Pair: docs/<codename>_starter.md + docs/<codename>_starter.json
# The JSON half is the profile oto loads; this file is context for you and
# the doc agents. See docs/starter_pair.md.

codename: <codename>

## Target

<!-- What is this device? Vendor, marketing name, where it lives (desktop,
     APU, laptop, datacenter). One or two lines. -->

## Why we're tuning for it

<!-- What workload, what goal (library build, benchmark coverage, gate
     calibration), what success looks like. -->

## Known quirks

<!-- Anything a doc agent should research and verify, e.g. instruction-set
     gaps, LDS/VGP pressure, driver quirks. List questions, not answers. -->

## Research brief (for the agents)

<!-- Specific questions the research should answer, e.g.:
     - What is the exact gfx ISA triple for this part?
     - CU count / SIMD layout for the specific SKU?
     - Base/boost clock and peak FP32?
     - First-party URLs (AMD ISA reference, ROCm release notes)? -->

## API key

<!-- Name the env var, never the key. e.g. "export ANTHROPIC_API_KEY=..."
     on the machine that runs `oto agent generate`. -->
