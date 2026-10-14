# corpus3.md — pass-3 research corpus (pointer)

**Status: FOLDED. 2026-10-14.** The durable content has been moved into the
ecosystem's single-home files. The original is preserved verbatim at
`archive/corpus3.pass3_20261014.md` — read it only for the raw sweep record, never
as an authority.

This file exists so a reader who arrives from `RESEARCH_PROMPT3.md` (which promises
a `corpus3.md`) is routed to the homes rather than to a stale duplicate. **Do not
re-derive from this file; cite the homes.**

Pass 3 was the residual brief (Q-A…Q-F) after passes 1–2 were mined: load/store
widths, scheduling/persistence, non-pow2 WGM, deep unroll, conditional follow-ups,
run protocol. All Tensile claims are pinned to `e8a8999e` with evidence labels.

## Where each part went

| corpus3.md section | home now |
|---|---|
| Q-A `LocalReadVectorWidth` / `StoreVectorWidth` / `DirectToLdsA/B` | `knowledge_base.md` §7.1 (default resolutions) + §7.2 (4-byte guard: CC/ZZ/DD illegal, SS/HH-only; no VGPR-saving rule; `gwvw` precedence) |
| Q-B scheduling/persistence table | `knowledge_base.md` §7.2 (SIA 2/3 refused; StoreRemap refused w/o MI; SGR/SLW unproven; StorePriorityOpt real but low-priority; PersistentKernel held) |
| Q-C WGM=7/14 | `knowledge_base.md` §7.2 + §8.4 (legal domain, traversal-block meaning, no CU binding) |
| Q-D `DepthU=32/64` + LDS table | Post-run follow-up, not decked: DU32 screens only on headroom tiles with PGR=0, DU64 only small-tile/one-buffer. Constraint recorded in `kernel_tuning_research.md` §9.2 |
| Q-E i (StaggerU×SUS), ii (APM=2), iii (PGR read guide) | (i) conditional follow-up, recorded here only; (ii) cap marked UNCONFIRMED in `knowledge_base.md` §7.2 + §8.4, APM row rationales corrected in `potential_configs.md` §8 + `oto/tensile/decks.py`; (iii) post-run read guide in `potential_configs.md` §10.6 |
| Q-F protocol + record schema | `knowledge_base.md` §8.3 steps 7–9 (randomize/MAD/flush rule/schema/telemetry-incomplete tagging) |
| Adoption matrix | Superseded by the homes above (no new legal candidate for this run) |
| Do-not-cite list (7 items) | `knowledge_base.md` §8.4 (5 new rows) |
| Concrete changes list | (a) LRVW=2 bounded differential, DU32 screen, SU×SUS pairing → post-run follow-ups, recorded in `kernel_tuning_research.md` §9.2; (b) SIA/StoreRemap/SGR/SLW/PersistentKernel/D2L-complex → do-not-propose, `knowledge_base.md` §7.2; (c) writer-forwarding gaps these imply → FIXED same day (`oto/tensile/config_writer.py`, `tests/test_writer_forwards_sweep_knobs.py`); (d) gate-hardening for D2L/SIA/StoreRemap → post-run follow-up (`kernel_tuning_research.md` §9.2) |

## What changed the run (load-bearing, 2026-10-14)

While folding Q-A/Q-B the port found its writer silently dropped nine sweep knobs
and collapsed two more (`bool(PGR=2)→1`, `WorkGroup[2]=1`): ~200 of the 270
emitted candidates would have benchmarked defaults. Fixed in
`oto/tensile/config_writer.py::_fork_params` (int forwarding for UseSgprForGRO,
InnerUnroll, NLCB, MaxOccupancy, APM, FractionalLoad, NonTemporalA/B, AF1EM;
PGR as int; LSU via `WorkGroup[2]`), guarded by
`tests/test_writer_forwards_sweep_knobs.py` (19). The 310-phase manifest was
re-verified after the fix. Home: `changelog.md` (2026-10-14 entry).
