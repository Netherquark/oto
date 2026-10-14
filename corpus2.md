# corpus2.md — pass-2 research corpus (pointer)

**Status: FOLDED. 2026-10-14.** The durable content has been moved into the
ecosystem's single-home files. The original is preserved verbatim at
`archive/corpus2.pass2_20261014.md` — read it only for the raw sweep record, never
as an authority.

This file exists so a reader who arrives from `RESEARCH_PROMPT2.md` (which promises
a `corpus2.md`) is routed to the homes rather than to a stale duplicate. **Do not
re-derive from this file; cite the homes.**

Pass 2 was a narrower brief than pass 1: the eleven Tensile knobs the corpus had
never set. Its own provenance note is important — parts of it are
source-inspection of *upstream* Tensile at a different version, not the pinned
`e8a8999e` checkout, so every row carries an evidence label
(`VERIFIED`/`PARTIAL`/`UNVERIFIED`/`REASONING`).

## Where each part went

| corpus2.md section | home now |
|---|---|
| §0 provenance, evidence labels | `archive/corpus2.pass2_20261014.md` (provenance is part of the raw record) |
| §1 executive synthesis, §4 adoption matrix, §5 prior-draft hypotheses | `knowledge_base.md` §7.2 (the mechanism-verified levers, with the "source-inspected, not measured" caveat) |
| §2 defaults table (wiki values with "check local `Common.py`") | **Superseded**: `knowledge_base.md` §7.1 holds the values read from the pinned checkout, and `oto/tensile/decks.py` `TENSILE_KNOB_DEFAULTS` is the machine-readable copy |
| Q1 `UseSgprForGRO` | `knowledge_base.md` §7.2; the deck row is in `oto/tensile/decks.py` `KNOB_SWEEPS` |
| Q2 `StaggerU`/`WorkGroupMapping` | `knowledge_base.md` §7.2 (the BufferLoad coupling) + `oto/tensile/gates/occupancy.py` `_swizzle_feasible` |
| Q3 `AggressivePerfMode`/`MaxOccupancy` | `knowledge_base.md` §7.2 (`DeviceLDS // N`, floor) |
| Q4 `LocalSplitU`/`GlobalSplitU` + 7-CU table | `potential_configs.md` §6 Route C (the `G`/`G mod 7`/utilisation table) and §8.1 (the gate's actual verdicts) |
| Q5 `NumLoadsCoalesced` | `knowledge_base.md` §7.2 — the derived-divisibility rule, not a byte predicate |
| Q6–Q9 `InnerUnroll`/`FractionalLoad`/`NonTemporal`/prefetch | `knowledge_base.md` §7.2 |
| Q10 strategy, §7 run plan | Not adopted as written — the project runs a deterministic one-shot pipeline (`tensile_tuning_context.md`); the deck encodes the priority. A run protocol (blocked order, reference-kernel drift tracking, floor telemetry) is re-briefed in `RESEARCH_PROMPT3.md` Q-F |
| §3 helper functions | Not adopted: the project already owns these in `oto/tensile/gates/`. Superseded by the gates |
| §6 evidence/exclusion ledger | `kernel_tuning_research.md` §9.2 (new rows) + §9.3 (resolved) |

## What the project's own measurement settles (supersedes corpus2 caveats)

1. **VGPR allocation granule.** corpus2 left "4 vs 8/16" open and told readers to
   pass `granule` explicitly. The project closed it: **granule 4**, fitting all ten
   rows of the AMD/ORNL GFX9 table, `python3 -m oto.harness.asm_occupancy
   --check-calibration` = 10/10. Home: `oto/harness/asm_occupancy.py`.
2. **Occupancy framing.** corpus2 inherited "low occupancy is the problem".
   Measured across 5,757 kernels, **LDS capacity binds 61.7%**, VGPR 22.4%, and
   only 2.1% run at ≤3 waves/CU. Home: `gfx90c_theoretical_limits.md` §7.1.
3. **`MaxOccupancy` rounding** is floor, not ceil. Home: `knowledge_base.md` §7.2.
4. **The defaults.** corpus2 gave wiki values; the pinned-checkout values are now
   in `knowledge_base.md` §7.1 and `TENSILE_KNOB_DEFAULTS`.
5. **The `GlobalLoadVectorWidth` guard.** corpus2's knob set included `GLVW`, and
   the gate now models Tensile's full shift-ptr rule (bufferLoad +
   `GuaranteeNoPartialA` + pv reduction) at the pinned commit: unpaired `GLVW=2`
   is refused or a no-op everywhere, and the one realizable widen (CC-only pair
   with `AssertFree0/1ElementMultiple=2`) is swept as a trial.
   Home: `oto/tensile/gates/loads.py`, `potential_configs.md` §8.1 + §9 D4.

## Companion corpora — mined 2026-10-14

`corpus2_cg.md`, `corpus2_claude.md`, `corpus2_gemini.md` were three other research
agents' answers to the same `RESEARCH_PROMPT2.md`. Each now carries a `MINED`
header recording its disposition:

- `corpus2_cg.md` — knob mechanics cross-checked against the pinned `e8a8999e`
  checkout and the gates (all consistent, none new); run-design advice folded
  into the run protocol. No new deck row.
- `corpus2_claude.md` — the `GlobalSplitUAlgorithm`/SingleBuffer lead already
  answered in-repo; VGPR granule settled at 4; wiki defaults verified.
  No new deck row.
- `corpus2_gemini.md` — Q1–Q9 consistent with the gates; Q10 matches the deck's
  priority order. No new deck row.

Residual questions from all three (load/store widths, scheduling/persistence,
non-pow2 WGM, deep unroll, conditional follow-ups, run protocol) are the brief
for the third pass: `RESEARCH_PROMPT3.md` → `corpus3.md`. The raw companion
bodies below their headers stay unedited — do not cite them; cite the homes.
