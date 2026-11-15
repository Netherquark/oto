# Device limits & ceilings — template (populated by the agent per device)
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


> **TEMPLATE — copy and fill per device.** Do not edit the golden example; populate this file for your target.

> **Status: TEMPLATE, NOT POPULATED.** This file ships with the repository as
> device-independent scaffolding. It becomes a real document only when an
> agent on a new target has probed the hardware and derived the ceilings from
> source + measurement. Until then it says what belongs here and how it
> gets here.
>
> The gfx90c port's derived ceilings live in `docs/gfx90c/gfx90c_theoretical_limits.md` —
> consult it as a golden reference / worked example **only if needed**, and
> never copy its numbers as the ceilings for another device. Ceilings are
> derived, not inherited; this whole file exists so that no agent treats one
> part's roof as another's.

## 1. ISA identity — prove, never assume

- Probe, don't recall: `rocminfo` ISA tuple, `rocminfo` name table,
  Tensile `GetAsmCaps`/`AsmCaps` on the pinned checkout, `rocminfo | grep -i gfx`.
- Record: ISA `(major,minor,stepping)`, CU/SIMD count, wavefront width,
  cache hierarchy (L1/L2/size), LDS capacity and banks/CU,
  MFMA/WMMA presence, supported matrix instructions, `HasDirectToLds`,
  `HasGLCModifier`, atomic add, FP16-fast paths, FP64 rate.
- Vendor "known bits" only as *hints*: verify each against the pinned
  Tensile source (`AsmCaps` in the exact commit — `GetAsmCaps` test-assembles
  on the real clang, so derived caps win over hand tables).

## 2. Peak derivation — lanes × clock × throughput

For every dtype family the port uses, derive:

- issue rate = `lanes × ops per lane per clock × clock`,
- unit width (scalar CL per cycle vs dual-issue packed paths),
- the 16-byte/vector-cap and the matrix-instruction presence/absence,
- complex/ceil availability (BLAS-8 accounting: one complex MAC = 4 real FMAs
  = 8 BLAS flops; the ÷4 trap is documented in `docs/gfx90c/gfx90c_theoretical_limits.md`).

Every peak needs the hardware basis stated (lanes/CU, CUs, wavefront, clocks),
not a number from another part.

## 3. Family table — fill per device

One row per family: `bytes/elem | peak | ridge (F/B) | square-MT at ridge |
legal TT at that MT | AI at measured winner | LDS cost | verdict bar`.
Include: the dtype vs the accumulator width, the LDS footprint model,
the register-file bound. Ridge arithmetic: `AI = flopsPerMac × MT0·MT1 /
((MT0+MT1) × bytesPerElement)`.

## 4. The acceptance bar this port uses

The ceiling set is the authority the report tool consumes
(`oto/metrics/acceptance_report.py`). State it explicitly:
which peaks, which tie band, how verdicts are computed, and which band
(`tie_band_pct`) — plus the measured reproducibility band beside it.

## 5. Populating this file — the order

1. Probe/derive §1 and §2 from the pinned sources + the chip itself.
2. Emit the §3 family table; mark any unverifiable cell `not found (read: …)`.
3. Wire the derived peaks into the port's report tool (`oto check
   ceilings` or the device profile) and prove the gates at 0/0 with the local
   corpus before any cell is graded against them (`oto.harness.gate_calibration`).
4. Record derivation commands, source pins and clocks in an appendix; date-stamp
   every ceiling.

## 6. Hard rules

- **No inherited numbers.** A peak copied from a table without the stated basis
  does not ship.
- **"Every claim traceable"** — line-annotated source pins; `not found
  (read: X)` beats a guess.
- **The ceiling is not the floor.** Verdicts compare native vs floor (and vs
  the roofs); this file supplies the roof, not the verdict.
- **gfx90c worked example**: `docs/gfx90c/gfx90c_theoretical_limits.md` (per-family
  ceilings, the gate census, the calibration method — read it only as a worked
  example of *how to derive*, never as a source of numbers).
