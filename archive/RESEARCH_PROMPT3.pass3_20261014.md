# RESEARCH_PROMPT3.md — the third research pass (residual questions only)

**What this is:** a short, sharply-targeted brief. Pass 1 (`RESEARCH_PROMPT.md`
→ `corpus.md`) settled the hardware and tile physics. Pass 2
(`RESEARCH_PROMPT2.md` → `corpus2.md`) settled the eleven never-varied knobs'
mechanisms, and the deck now sweeps them (`oto/tensile/family_decks.py`
`KNOB_SWEEPS`, `docs/potential_configs.md` §8.1) plus decision-labelled trials
(`DECISION_TRIAL_TILES`, §9 D1–D4). This pass asks only what is *still* open
after both corpora were mined — six question groups, no more.

**Spawn into a max-effort research agent.** It has **no GPU access** and must not
run anything that needs one. It is a *literature and documentation* agent. It
writes exactly one file: `corpus3.md`.

**What changed since pass 2 (accept as given, do not re-derive):**

* The sweep deck covers every pass-2 knob: UseSgprForGRO, InnerUnroll,
  PrefetchGlobalRead 1/2, NumLoadsCoalescedA/B=2 (with width_override),
  MaxOccupancy 8/12/20, AggressivePerfMode 1/2, GlobalSplitU 2/4 (SS/DD only),
  LocalSplitU=2, StaggerU 0/8/16, FractionalLoad=1, NonTemporalA/B, plus the
  CC-only paired widen `GLVW=2 + AssertFree0/1ElementMultiple=2` and explicit
  `_base` controls (`knob_sweep --baseline`). Do not re-justify these rows.
* The gate models Tensile's full shift-ptr GLVW rule (bufferLoad +
  GuaranteeNoPartialA + pv reduction) at the pinned commit; unpaired `GLVW=2`
  is refused or a no-op everywhere. Do not re-litigate GLVW.
* `BYTES_PER_ELEMENT["Z"]=8` vs 16 + `LDS_BUDGET` is a user-owned pair (16/32768
  preserves the boundary); ZZ VW2 is decked as the differentiator trial. Do not
  re-argue the byte count — report only behaviour-changing consequences.
* VGPR allocation granule is **4** on gfx9 wave64 (measured 10/10 AMD/ORNL GFX9
  rows). Do not re-open it.
* `*Read2A/B` is a dead path upstream ("not used yet", `Common.py:612`); hold
  until local emitted ISA proves otherwise. Do not propose sweeping it.
* `GlobalSplitUAlgorithm=MultipleBuffer` + workspace is not forwarded by this
  port's writer; only the SingleBuffer-atomic path is reachable. Do not propose
  complex GSU through it.

---

## THE PROMPT — copy from here down

You are a GPU microarchitecture and kernel-tuning research agent. Today is
2026-10-14. Your output is a single file, `corpus3.md`, read by another agent
that is tuning AMD GEMM knobs on a specific part. Write for someone who knows
what a GEMM is and who has already read `corpus.md` and `corpus2.md`.

## §H GROUND TRUTH — accept as given, deltas from pass 2 only

Part: gfx90c (Renoir/Cezanne Vega-8 APU), 7 CUs, wave64, no MFMA/dp4a,
64 KB LDS/CU, 1 MB L2, ~40–42 GB/s shared DDR4, peaks FP32 1613 / FP16 3226 /
FP64 101 / complex `flopsPerMac = 8`. Tensile v4.44 at pinned commit `e8a8999e`,
emits GCN ISA text. Verdicts 19 WIN / 18 TIE / 1 LOSS (CC:256, a floor-arm
telemetry artifact). Complex is issue-bound (4 real FMAs per MAC); LDS binds
61.7% of kernels; median 8 waves/CU; zero spills. Full tables:
`docs/potential_configs.md` §§1,8–9, `docs/knowledge_base.md` §7, `docs/research/kernel_tuning.md`
§§9.1–9.3, `docs/gfx90c_theoretical_limits.md` §§6–7.

**Provenance rule (non-negotiable):** every claim about Tensile behaviour must be
traced to the *pinned* `e8a8999e` checkout (`Tensile/Common.py` defaults block
`:1507-1670`, `SolutionStructs.py`), not to upstream `develop`, the obsolete
wiki, or a different version. Label every row `VERIFIED` (pinned source read),
`PARTIAL` (release notes / other-version source / snippet), or `REASONING`.
Literature numbers are priors, never conclusions.

## §Q — six groups, nothing else

**Q-A. Load/store widths never swept.** `LocalReadVectorWidth` (default `-1`,
domain `[-1,1,2,4,8,16]`), `StoreVectorWidth` (default `-1`, domain includes
`3,6`), `DirectToLdsA/B` (default `False`). For each: what the `-1`/`False`
resolves to on a gfx90c Assembly kernel at `e8a8999e` (exact function + line),
which guards constrain it (divisibility, TLU/TLU-free, transpose), and the
predicted direction per family — in particular whether narrowing
`LocalReadVectorWidth` to 2 relieves the VGPR-bound CC/ZZ tiles, and whether
`DirectToLds` (skip VGPR staging) helps or hurts on a part where LDS binds
61.7% of kernels. Flag anything that, like `*Read2`, is parsed but unimplemented
in the local writer.

**Q-B. Scheduling and persistence.** `PersistentKernel` (present in
`Common.py`, *not* forwarded by this port's writer), `ScheduleGlobalRead`,
`ScheduleLocalWrite`, `ScheduleIterAlg`, `StorePriorityOpt`, `StoreRemapVectorWidth`.
For each: the mechanism at `e8a8999e`, whether the Assembly writer honours it on
a non-MI target, and the predicted effect on an issue-bound complex kernel.
For `PersistentKernel` specifically: is it settable through this writer at all,
and would a persistent grid change the 7-CU tail arithmetic (tail = `G mod 7`)?

**Q-C. Non-power-of-two WorkGroupMapping.** The deck uses WGM 4/8. The gate
models no WGM constraint. Does Tensile accept WGM 7/14 on gfx90c Assembly, what
does the value do to the workgroup raster exactly (function + line), and is
there any measured or reasoned case that matching the raster to the 7 physical
CUs helps the small-shape cells (256/192)? `VERIFIED`-only; a "7 is natural"
argument without a source is `REASONING`.

**Q-D. Deep unroll.** The deck's max `DepthU` is 16. What refuses `DepthU=32/64`
per family at `e8a8999e` (LDS budget arithmetic with the family's byte width,
VGPR, `InnerUnroll` divisibility `DepthU % (LSU*InnerUnroll) == 0`), and where
— if anywhere — does a legal deep tile exist? Weigh ILP gain against the
occupancy cost on the measured 8-waves/CU median. Candidates, not conclusions.

**Q-E. Conditional follow-ups (answer as conditionals, do not assume the run).**
(i) `StaggerUStride`/`StaggerUMapping` pairing — *only* worth sweeping if the
run shows `StaggerU` itself moves anything; state the exact pairing to try
(PR #10847 did SU 32→16 + SUS 256→128 on gfx1100 WMMA: `PARTIAL`, do not
over-claim). (ii) `AggressivePerfMode=2`'s writer path — confirm the mode-2 LDS
cap in local source or mark it unconfirmed. (iii) `PrefetchGlobalRead=0 vs 1`
on the complex winners — the run measures both (`PLAN_BATCH` PGR=0 vs sweep
PGR=1/2); state what a 0-wins / 2-wins / 1-wins outcome each implies.

**Q-F. Run protocol.** The 10h run needs: blocked/randomized phase order with a
reference-kernel interleave for drift detection, 25% warmup, L2-flush policy per
shape class, sclk pin + per-phase clock/temperature logging, and the floor-arm
telemetry fix for CC:256 (record `spoof_clock_sclk_hz` coverage; `D1`). Cite the
AMD MAF protocol and one independent source for each recommendation. Keep it to
what this specific APU run needs — no generic benchmarking essay.

## §P — do not re-ask (already settled, asking again wastes the pass)

`GroupSegmentFixedSize`, `LoopUnroll` (not real Tensile knobs — 0 hits in
`Common.py`); unpaired `GLVW` (refused/no-op); `BufferLoad` as a row (no-op);
`*Read2` (dead); complex `GlobalSplitU` via `MultipleBuffer` (unreachable);
the `Z`-byte pair (user-owned); VGPR granule (4, measured); WGM 4/8 and all
§8.1 rows (swept); MT caps ≤64 (contradicted by the MT128 winners).

Output `corpus3.md`: §Q answers with evidence labels, a one-table adoption
matrix (knob × mechanism-verified? × predicted family × confidence), and a
do-not-cite list. No other file.
