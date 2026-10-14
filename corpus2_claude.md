# corpus2.md — knob research, pass 2 (PARTIAL RUN)

> **Status: MINED 2026-10-14.** The `GlobalSplitUAlgorithm`/SingleBuffer+AtomicAdd
> lead is already answered in-repo (only the SingleBuffer-atomic path is
> reachable; `oto/tensile/gates/assembly.py`, `kernel_tuning_research.md`); the
> VGPR-granule flag is settled at 4 (`--check-calibration` 10/10); the wiki
> defaults were verified against the pinned checkout (`knowledge_base.md` §7.1).
> **No new deck row came out of this file.** The StaggerU↓+SUS-scale pairing
> (from PR #10847, gfx1100 WMMA — PARTIAL) is a conditional follow-up in
> `RESEARCH_PROMPT3.md`. Raw below — do not cite; cite the homes.

**Scope honesty.** This run made 3 searches and 1 page fetch. It could NOT open Tensile's
`Common.py`, `Solution.py` or `KernelWriterAssembly.py` (search returned no source text, and
fetch only accepts URLs already seen), so there are **no `file:line` citations** and most of
Q2–Q10 remain open. §H was used as given. Markers: VERIFIED = read the source text;
PARTIAL = excerpt/summary only; UNVERIFIED = not found / not attempted; REASONING = my
inference, no source.

## 0. Two flags before anything else

1. **The two briefs disagree on the VGPR allocation granule.** Pass 1 §H: 8 (≤96) else 16.
   Pass 2 §H: 4 on gfx9 wave64. I did not find a source for either. My unsourced recollection
   is 4, but resolve it from `getVGPRAllocGranule` in LLVM's AMDGPU backend before relying on
   any occupancy arithmetic. The function in §4 takes the granule as a parameter.
2. **A knob not on your §H.1 list matters for Q4:** `GlobalSplitUAlgorithm`
   (SingleBuffer / MultipleBuffer). It is in Tensile's obsolete wiki parameter table (default
   `SingleBuffer`) and in release notes (below). §H.1 neither lists nor forbids it. Whether the
   project's YAML can set it is your call.

## 1. Executive summary

* **Q4 lead (most consequential):** Tensile 4.37.0 release notes say "Added SingleBuffer
  algorithm for ZGEMM/CGEMM" and "SingleBuffer + AtomicAdd option for GlobalSplitU". So
  the "GlobalSplitU>1 illegal on complex" result on your v4.44 gate may be conditional on
  the `GlobalSplitUAlgorithm` / `AtomicAdd` setting rather than fundamental. Worth one probe
  before concluding complex cannot split K. PARTIAL (release notes only; v4.44 reject logic
  not read).
* **Q1:** `UseSgprForGRO` has a real, documented use as a VGPR-pressure relief, in a
  different arch: an AMD hipBLASLt retune on gfx1100 sets it `-1 → 1` and says it "reduces
  vector-register pressure" because global-read offsets are wave-uniform. No gfx9/gfx90c
  measurement found. PARTIAL.
* **Defaults matter for "never varied":** per Tensile's (obsolete, Dec-2024) wiki, the
  defaults of the knobs you call un-varied are `MaxOccupancy=40`, `AggressivePerfMode=1`,
  `InnerUnroll=1`, `FractionalLoad=0`, `UseSgprForGRO=-1`, `NumLoadsCoalescedA/B=1`,
  `PrefetchGlobalRead=True`, `PrefetchLocalRead=1`, `LocalRead2A/B=True`,
  `StaggerU=32`, `StaggerUStride=256`, `StaggerUMapping=0`, `BufferLoad=True`,
  `WorkGroupMapping=8`. So "unset" is not "off"; the baseline already includes
  APM=1, PGR on, LR2 on. Check these against your local 4.44 `Common.py`. VERIFIED (wiki
  text), but wiki is flagged obsolete.

## 2. Sources actually read

| source | what it gave | marker |
|---|---|---|
| Tensile wiki "Kernel Parameters" https://github.com/ROCm/Tensile/wiki/Kernel-Parameters | one-line parameter meanings + full kernel-name/default table (above); GlobalSplitU description | VERIFIED, **obsolete (Dec 2024)** |
| Tensile release 4.41.0 / ROCm 6.2.0 https://github.com/ROCm/Tensile/releases/tag/rocm-6.2.0 | `GlobalLoadVectorWidthA/B` added, "effective with GlobalReadVectorWidth=-1"; GSUA falls back to SingleBuffer when GSU=1 | PARTIAL (release notes) |
| Tensile release 4.37.0 / ROCm 5.6.0 https://github.com/ROCm/Tensile/releases/tag/rocm-5.6.0 | SingleBuffer for ZGEMM/CGEMM; SingleBuffer+AtomicAdd GSU; improved SingleBuffer GSU perf; complex VGPR allocation fix | PARTIAL |
| rocm-libraries PR #10847 https://github.com/ROCm/rocm-libraries/pull/10847 | `UseSgprForGRO -1→1`, `StaggerU 32→16`, `StaggerUStride 256→128`, `NonTemporalA 0→3` in a gfx1100 (WMMA) retune of a latency-bound small-N solution | PARTIAL (snippet; truncated) |

## 3. §Q answers

**Q1 UseSgprForGRO.** What it moves: per PR #10847, global-read offsets, rationale that they
are wave-uniform and "do not belong in vector" registers. Whether *every* address or only a
base moves, SGPR cost, scalar-issue contention with FMA, and interaction with
GlobalLoadVectorWidth/NumLoadsCoalesced/BufferLoad: **UNVERIFIED** (need
`KernelWriterAssembly.py`/`Solution.py`). Observation: in that PR the knob was changed together
with deeper pipelining, because it "relieves register pressure so the deeper pipeline fits"
— i.e. used as an enabler for other knobs, not alone. For your 63-VGPR complex-double tile,
test it alone first and together with PGR/PLR. Default `-1` (auto) means "unset" may already
be choosing 0 or 1 by a rule I did not find. UNVERIFIED which.

**Q2 StaggerU.** Defaults StaggerU=32, StaggerUStride=256, StaggerUMapping=0 (wiki). Mechanism
not read. The gfx1100 PR changed it to 16/128 for a latency-bound small-N solution — evidence
the vendor tunes it per shape, not a constant (PARTIAL). Non-power-of-two CU raster work: none
found (I did not search for it specifically). WorkGroupMapping wiki text: "In what order will
work-groups compute C; affects cacheing." Interaction with StaggerU: UNVERIFIED.

**Q3 AggressivePerfMode / MaxOccupancy.** Defaults APM=1, MaxOccupancy=40 (wiki). The
"mode 2 caps to 2 waves/SIMD via LDS" and "`64 KB / N` padding" claims are from your brief; I
did not confirm either in source. Literature on deliberately capping: not found. UNVERIFIED.

**Q4 Split-K.**
* Cost model (older description): GlobalSplitU "launches a kernel to handle the beta scaling,
  then a second kernel where the writes to global memory are atomic" (wiki). Later releases
  added `GlobalSplitUAlgorithm` SingleBuffer/MultipleBuffer (default SingleBuffer) and a
  second summation kernel for MultipleBuffer. PARTIAL.
* Complex legality: see §1 lead. Fundamental vs policy: the release notes imply a supported
  path exists for CGEMM/ZGEMM; REASONING: atomic add on a complex accumulator is two
  independent real adds, so correctness need not forbid it. Not confirmed in source.
* `LocalSplitU`: wiki lists it only as `WorkGroup[2]`; cost/divisibility UNVERIFIED. Note
  your brief describes it as splitting the MacroTile M extent across waves; the wiki
  describes `DepthU` as `LoopUnroll*SplitU`, i.e. it splits the **summation** across
  waves inside a workgroup. That is a discrepancy with the brief's description (the wiki is
  obsolete, so check the local source), and the difference matters: a summation split needs an
  LDS reduction at the end and does not add workgroups.
* Quantization arithmetic: §4 function.

**Q5 NumLoadsCoalesced.** Wiki: "Number of loads from A in coalesced dimension." Default 1.
The legality rule: **not found**. I will not guess one. UNVERIFIED.

**Q6 InnerUnroll.** Default 1 (wiki). Semantics and register relationship: UNVERIFIED.
Wiki says `LoopUnroll` "helps loading coalesced memory" and `DepthU` = LoopUnroll×SplitU.

**Q7 FractionalLoad.** Default 0. Semantics UNVERIFIED.

**Q8 NonTemporalA/B.** Defaults 0. The gfx1100 PR sets NonTemporalA 0→3 for a latency-bound
shape, so it is a tunable AMD actually moves (3 is a cache-policy code whose meaning I did
not look up). APU-specific measurements: not found. UNVERIFIED.

**Q9 Prefetch/LR2/GR2.** Defaults PGR=True, PLR=1, LR2A/B=True, GR2A/B=True (wiki). Since PGR
defaults True, your three complex winners with `PrefetchGlobalRead=False` are an explicit
departure from the default, not an unset value — worth confirming in the YAML. Whether LR2/GR2
double LDS capacity: UNVERIFIED. (`1LDSBuffer` default 0 per wiki; per its name it affects LDS
buffering — semantics unconfirmed.)

**Q10 Direction.** No GEMM-knob ablation ranking found. The AMD PR above is weak evidence
that vendor retuning for latency-bound shapes moves UseSgprForGRO, NonTemporal, StaggerU and
pipeline-depth knobs together, which argues against strictly one-knob-at-a-time (knobs are
used jointly) — REASONING from a single PR on a different arch. Expected yield: **unknown;
no evidence either way found.**

## 4. Legality / arithmetic functions

```python
import math
# Occupancy from §H. GRANULE is UNRESOLVED (4 per brief 2; 8/16 per brief 1) — pass it in.
def waves_per_simd(vgpr_per_thread, wg_threads, lds_bytes_per_wg,
                   granule=4, max_waves_simd=10, lds_per_cu=65536, simds=4):
    alloc = math.ceil(vgpr_per_thread / granule) * granule
    by_vgpr = 256 // alloc                       # 256 VGPR rows per SIMD (16384 regs / 64 lanes)
    waves_per_wg = wg_threads // 64
    wg_by_lds = lds_per_cu // lds_bytes_per_wg if lds_bytes_per_wg else 10**9
    wg_by_vgpr = (min(by_vgpr, max_waves_simd) * simds) // waves_per_wg
    wg_by_waves = (max_waves_simd * simds) // waves_per_wg
    return min(wg_by_lds, wg_by_vgpr, wg_by_waves)   # resident workgroups per CU

# Tail efficiency on 7 CUs, assuming `resident` WGs per CU and equal tile time.
def tail_efficiency(M, N, MT, NT, cus=7, resident=1, gsu=1):
    wgs = math.ceil(M / MT) * math.ceil(N / NT) * gsu
    slots = cus * resident
    return wgs / (slots * math.ceil(wgs / slots))
```
These are derived from §H, not from a source. `tail_efficiency` ignores per-tile cost; it
does not by itself choose the best tile (that also needs the reuse trade-off and, for
`gsu > 1`, the reduction cost). I did **not** derive the NLCA rule or the MaxOccupancy
padding formula.

## 5. Techniques table (partial)

| knob | source | changes in kernel | reg/LDS cost | expected direction | confidence |
|---|---|---|---|---|---|
| UseSgprForGRO | rocm-libraries PR #10847 | moves wave-uniform GRO to SGPR | −VGPR, +SGPR | VGPR-bound tiles (63 VGPR ZZ) | PARTIAL, other arch |
| GlobalSplitU + GlobalSplitUAlgorithm | Tensile 4.37.0/4.41.0 notes | splits K, SingleBuffer (+atomic) | extra kernel/atomics | complex may be legal under SingleBuffer | PARTIAL |
| StaggerU/Stride | PR #10847 | tuned per shape (32→16, 256→128) | none known | try 16 for small shapes | PARTIAL, other arch |
| NonTemporalA | PR #10847 | cache hint | none | unknown on APU | PARTIAL |
| rest | — | — | — | — | UNVERIFIED |

## 6. Could not verify / do not cite

* Everything in Q2 mechanism, Q3, Q5, Q6, Q7, Q9 semantics, Q10 yield.
* The pass-1 unverified items (ASPLOS'20 "Tile", 2507.15277 "142k tuples", gfx1151 clock
  result, COSTA/BASS/BEST/GemmLab): **not attempted** this run. Still do not cite.
* The wiki is marked obsolete by its own banner; defaults may differ in 4.44.
* PR #10847's text was truncated in the snippet; I read the quoted lines only.

## 7. What this changes

* Probe `GlobalSplitU=2..4` with `GlobalSplitUAlgorithm=SingleBuffer` (± AtomicAdd) on CC/ZZ
  before declaring complex K-split illegal — if the knob is settable.
* Test `UseSgprForGRO=1` on the 63-VGPR ZZ tile alone, then with `PrefetchGlobalRead`/
  `PrefetchLocalRead` raised (the enabler pattern in PR #10847).
* Confirm whether `PrefetchGlobalRead=False` on three complex winners is explicit vs default.
* Vary `StaggerU` down (16, 8) with `StaggerUStride` scaled together for small shapes.
* Resolve the VGPR granule (4 vs 8/16) from LLVM before trusting occupancy numbers.
* Confirm `LocalSplitU` semantics (summation split vs M split) in local source before
  spending candidates on it.
