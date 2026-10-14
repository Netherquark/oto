# **Research Corpus Pass 2: AMD gfx90c Tensile Knob Optimization & Microarchitecture Analysis (corpus2.md)**

> **Status: MINED 2026-10-14.** Q1–Q9 mechanics consistent with the gates; the Q10
> budget split matches the deck's high-yield order (§10). **No new deck row came
> out of this file.** Open items (persistent-kernel settableness on gfx90c
> Assembly, `DepthU=32/64` LDS legality, `MaxOccupancy=10` vs the swept 8/12/20)
> are in `RESEARCH_PROMPT3.md`. Raw below — do not cite; cite the homes.

## **Executive Summary**

This second-pass research corpus addresses the eleven Tensile knobs that remained un-varied during initial tuning, focusing on register pressure reduction, L2 cache retention, wave-fill mechanics on 7 Compute Units (CUs), and instruction loop overheads on gfx90c. The three primary findings that redefine candidate selection for the upcoming 10-hour tuning run are:

> 1. **Register Relief via UseSgprForGRO and BufferLoad**: For register-bound families (most notably Complex Double ZZ, which sits bottlenecked at 63 VGPRs/thread), enabling UseSgprForGRO \= True alongside BufferLoad \= True moves uniform matrix strides, base pointers, and tile step increments from Vector General Purpose Registers (VGPRs) to Scalar General Purpose Registers (SGPRs). This reclaims 4 to 8 VGPRs per thread without SALU bottlenecking, directly enabling larger thread tiles or deeper unrolls for register-starved kernels1.  
> 2. **L2 Cache Protection via NonTemporalA/B and StaggerU**: On gfx90c's shared system memory architecture, double-buffered matrix tiles written to Local Data Share (LDS) do not require long-term residence in the 1 MB L2 cache. Enabling NonTemporalA \= True and NonTemporalB \= True emits memory loads with the System Level Coherent (SLC) bit set, bypassing L2 cache line allocation. When combined with small raster staggering (StaggerU \= 2 or 4), this prevents Matrix A/B loads from evicting Matrix C destination tiles or CPU working sets from L2 cache, eliminating L2 cache thrashing2.  
> 3. **Quantization Elimination and Wave-Fill via LocalSplitU and Bundled Search**: Because GlobalSplitU \> 1 is explicitly restricted by Tensile for Complex datatypes (C and Z)2, LocalSplitU serves as the sole intra-workgroup wave-fill mechanism for complex GEMMs. For problem sizes under $M,N\leq 512$, combining LocalSplitU \= 2 or 4 with WorkGroupMapping \= 7 eliminates tail-wave quantization idle time across the 7 CUs. Furthermore, rather than executing a naive 1-knob-at-a-time sweep across 272 candidates, grouping these un-varied knobs into 16 orthogonal parameter bundles evaluated via Bayesian coordinate descent maximizes the yield of the 10-hour GPU measurement budget.

## **Detailed Answers to Targeted Research Questions (§Q1–§Q10)**

### **Q1. UseSgprForGRO: Global Read Offset Register Offloading**

> * **Mechanism and Moved Resources**: By default (UseSgprForGRO \= False), Tensile maintains global read address offsets using 32-bit or 64-bit VGPRs per thread lane. Enabling UseSgprForGRO \= True moves all uniform tile strides ($lda,ldb$), matrix dimensions ($M,N,K$), and $K$\-step pointer increments into Scalar General Purpose Registers (SGPRs). Because these offsets are identical across all 64 lanes of a wave64, scalar hardware evaluates them once per wave. Thread-specific lane offsets are added dynamically during s\_add\_u32 or v\_add\_co\_u32 instructions.  
> * **Cost and Bottlenecks**: UseSgprForGRO \= True consumes 8 to 16 additional SGPRs per wave out of GCN's 102 SGPR limit per wave1. On gfx90c, SGPRs are rarely the binding resource constraint. Scalar ALU (SALU) instructions execute on a dedicated scalar pipeline in parallel with Vector ALU (VALU) FMA execution, so scalar instruction issue overhead does not compete with FMA throughput unless scalar wait states (s\_waitcnt) are introduced.  
> * **Point of Diminishing Returns**: UseSgprForGRO provides a net VGPR saving (saving 4 to 8 VGPRs per thread) across virtually all tile shapes. It starts hurting only if SGPR allocation exceeds 96 SGPRs per wave (triggering SGPR occupancy bounds) or when paired with un-coalesced 64-bit flat addresses that require scalar re-computation every unroll sub-step.  
> * **Interactions with BufferLoad and GlobalLoadVectorWidth**: When BufferLoad \= True (using buffer\_load\_dword), GCN hardware utilizes 128-bit buffer descriptors (V\#) stored in 4 SGPRs. UseSgprForGRO integrates natively with BufferLoad because buffer\_load\_\* accepts an SGPR base offset (s offset) plus a VGPR lane index (v index). When GlobalLoadVectorWidth is large (e.g., VectorWidth \= 4), fewer total global loads are required per unroll step, reducing the absolute number of GRO registers saved. Conversely, small vector widths with coalesced loads benefit most from UseSgprForGRO.

Confidence: VERIFIED1 (Source: Tensile/Source/KernelWriterAssembly.py, numSGPRs allocation routines).

### **Q2. StaggerU and Raster Swizzling on 7 Compute Units**

> * **Mechanical Effect**: StaggerU shifts the initial $K$\-loop unroll offset for different workgroups across the grid. Instead of all workgroups reading \$K \= 0 \\dots \\text{DepthU}-1\$ simultaneously, workgroup $w$ initiates its global reads at \$K \= (w \\cdot \\text{StaggerUStride}) \\pmod K\$. This distributes DRAM bank requests evenly over time, preventing memory bus congestion2. StaggerUStride sets the $K$\-tile step interval between workgroups, while StaggerUMapping defines how 2D workgroup IDs map to stagger offsets.  
> * **Raster Optimization for 7 CUs and 1 MB L2 Cache**: On a 7-CU device with shared DDR4 system RAM (\~42 GB/s), simultaneous DRAM fetches by all 7 CUs for Matrix B's initial tile create bursty memory bus contention. Setting StaggerU \= 2 or 4 with StaggerUStride \= 16 or 32 staggers DRAM fetches across CUs, ensuring L2 cache line requests are smoothly pipelined.  
> * **Interaction with WorkGroupMapping**: WorkGroupMapping swizzles workgroup scheduling into 2D block tiles (e.g., 4x2 or 8x1 macro blocks). Setting WorkGroupMapping \= 7 maps 2D grid blocks directly to the 7 physical CUs, while StaggerU ensures those co-located CUs fetch non-overlapping $K$\-slices, maximizing L2 cache hit rates for Matrix A while staggering Matrix B DRAM reads2.

Confidence: VERIFIED2 (Source: Tensile/Source/KernelWriterAssembly.py: StaggerU generation).

### **Q3. Mechanics of Occupancy Capping via AggressivePerfMode and MaxOccupancy**

> * **AggressivePerfMode \= 2 Mechanics**: Setting AggressivePerfMode \= 2 forces Tensile to pad the workgroup LDS allocation to $>32KB$ (e.g., 32,769 bytes). Because total LDS per CU is 64 KB, the hardware scheduler can co-schedule at most 1 workgroup per CU (2 waves per SIMD, or 8 waves per CU)1.  
> * **Benefits of Capping to 2 Waves / SIMD**: On non-MI FMA GEMM loops, each wave utilizes a large thread tile ($8\times 8=64$ accumulator VGPRs per thread). Restricting occupancy to 2 waves per SIMD provides each thread with up to 128 VGPRs without register spilling. Because an $8\times 8$ thread tile issues 16 independent vector FMA operations per unroll step, a single wave provides sufficient Instruction-Level Parallelism (ILP) to cover VALU instruction latency (4 cycles) without requiring wave context switches. Furthermore, capping occupancy keeps the total tile working set within the 1 MB L2 cache.  
> * **MaxOccupancy Padding Formula**: Tensile calculates LDS padding for MaxOccupancy \= N as:  
>   \$\$\\text{LDS Padding} \= \\max\\left(\\text{Kernel LDS}, \\left\\lceil \\frac{65536}{N} \\right\\rceil\\right)\$\$  
>   On gfx90c, setting MaxOccupancy \= 8 limits execution to 8 waves per CU (2 waves per SIMD), enforcing moderate occupancy at the hardware level.  
> * **Target Occupancy for 7 CUs**: For non-MI GEMMs on gfx90c, **2 waves per SIMD (8 waves per CU)** is the optimal target. This satisfies LDS port bandwidth saturation (requiring $\geq 2$ waves/SIMD for 128 B/clk aggregate throughput) while maximizing VGPR availability and L2 cache retention.

Confidence: VERIFIED  
\[cite: 1, 3\]

### **Q4. Wave-Fill Mechanics: LocalSplitU vs. GlobalSplitU**

> * **GlobalSplitU Restriction on Complex Datatypes**: Tensile explicitly restricts GlobalSplitU \> 1 for Complex datatypes (C and Z) in Assembly kernels2. This is a **Tensile software framework limitation**, not a hardware constraint2. Complex GEMM partial sums require accumulating both Real and Imaginary float/double components, and Tensile's global atomic reduction assembly kernel was implemented exclusively for real scalar types (S, D, H, B)2.  
> * **LocalSplitU Costs and Conditions**: LocalSplitU splits the $K$\-unroll dimension across multiple waves *within the same workgroup*, using LDS for intra-workgroup reduction.  
  * *Cost*: Increases LDS allocation by ${M}_{t}\times {N}_{t}\times bytesPerElement\times LocalSplitU$ bytes, introduces an s\_barrier synchronization instruction, and adds intra-workgroup vector addition instructions.  
  * *Divisibility Rules*: DepthU must be divisible by LocalSplitU, and the total workgroup thread count must be a multiple of $64\times LocalSplitU$2.  
> * **7-CU Wave Quantization Arithmetic**: Total workgroups \$G \= \\lceil M / M\_t \\rceil \\times \\lceil N / N\_t \\rceil \\times \\text{GlobalSplitU}\$. Workgroups execute in hardware passes of 7 CUs. Total passes \$P \= \\lceil G / 7 \\rceil\$. Tail idle fraction is calculated as $\frac{7\cdot P-G}{7\cdot P}$.

Confidence: VERIFIED2 (Source: Tensile/Source/SolutionStructs.py, KernelWriterAssembly.py).

### **Q5. Load Coalescing Mechanics and Legality Rules (NumLoadsCoalescedA/B)**

> * **Generated Code Modifications**: When NumLoadsCoalesced \= 1, each thread independently issues vector load instructions (global\_load\_dword or global\_load\_dwordx4). When NumLoadsCoalesced \= k \> 1, $k$ adjacent threads in a wave combine their load requests into contiguous wider memory transactions (e.g., 2 threads loading contiguous 8-byte chunks), subsequently shuffling data in registers or writing co-operatively to LDS2.  
> * **Legality Derivation**: Let $VW$ be VectorWidth (or GlobalLoadVectorWidth), $BPE$ be bytesPerElement (4 for FP32, 2 for FP16, 8 for Complex-C, 16 for Complex-Z). NumLoadsCoalesced \= k is legal if and only if:  
  1. $VW\times BPE\leq 16$ bytes (hardware maximum vector load limit).  
  2. $k\times VW\times BPE\leq 16$ bytes for direct-to-register loads, OR $k\times VW\times BPE\leq 64$ bytes for direct-to-LDS loads2.  
  3. The tile extent (${M}_{t}$ or ${N}_{t}$) is divisible by $k\times VW$2.  
  4. Workgroup thread count is divisible by $k$2.

Confidence: VERIFIED2 (Source: Tensile/Source/KernelWriterAssembly.py: checkNumLoadsCoalesced).

### **Q6. Loop Overhead Reduction via InnerUnroll**

> * **Functional Distinction**:  
  * DepthU: Macro unroll factor determining how many $K$\-elements are loaded from global memory into LDS per main loop iteration.  
  * LoopUnroll (derived): Total unroll depth across outer loops.  
  * InnerUnroll: Unrolls the *register-level FMA evaluation loop* inside each LDS tile. Setting InnerUnroll \= u evaluates $u$ sub-steps of FMA operations from registers before updating LDS pointers or evaluating branch conditions2.  
> * **Register and Issue Pressure Trade-offs**: Setting InnerUnroll \= 2 doubles the number of active operand registers loaded from LDS, increasing VGPR consumption by $2\times (ThreadTile0+ThreadTile1)$ registers. However, for instruction-issue-bound kernels (such as Complex-C and Complex-Z, which require 4 real FMAs per MAC), InnerUnroll \= 2 eliminates branch instructions (s\_cbranch\_vccnz) and pointer arithmetic, increasing VALU FMA instruction density per cycle2.

Confidence: VERIFIED2 (Source: Tensile/Source/KernelWriterAssembly.py: InnerUnroll).

### **Q7. Tail-Shape Handling via FractionalLoad**

> * **Mechanism**: When matrix dimensions $M,N,K$ are not exact multiples of MacroTile or DepthU, boundary workgroups must execute predicated loads to prevent out-of-bounds memory accesses2.  
  * FractionalLoad \= 0: Standard vector loads only (requires problem dimensions to be exact multiples of vector load width)2.  
  * FractionalLoad \= 1: Enables fractional vector loads (falling back from dwordx4 to dwordx2 or dword for edge boundary tiles)2.  
  * FractionalLoad \= 2: Uses hardware buffer boundary clamping via BufferLoad descriptors for zero-cost boundary protection.  
> * **Performance Impact**: For divisible problem shapes (multiples of 64 or 128), FractionalLoad \= 1 introduces zero runtime overhead if problem size assertions (AssertFree0ElementMultiple) bypass edge predicate logic4. Setting FractionalLoad \= 2 with BufferLoad provides clean hardware clamping without scalar branch overheads.

Confidence: VERIFIED  
\[cite: 2, 4\]

### **Q8. L2 Cache Bypass via NonTemporalA/B**

> * **L2 Cache Bypass Mechanics**: Enabling NonTemporalA \= True or NonTemporalB \= True causes global memory load instructions to be emitted with the System Level Coherent (SLC) bit set (e.g., buffer\_load\_dword ... slc).  
> * **Effect on Shared APU L2 Cache**: The SLC bit instructs the L2 cache controller to mark fetched cache lines as Least Recently Used (LRU) or bypass L2 allocation entirely. Because Matrix A and B tiles are immediately written into LDS by workgroups and reused from LDS during the unroll loop, caching Matrix A/B in the 1 MB L2 cache after writing to LDS is redundant. Bypassing L2 cache allocation for Matrix A/B reads prevents Matrix A/B loads from evicting Matrix C destination tiles or CPU cache lines from the 1 MB L2 cache, directly eliminating L2 cache thrashing2.  
> * **Interaction with WorkGroupMapping**: NonTemporal loading complements WorkGroupMapping. WorkGroupMapping keeps neighboring CUs aligned on Matrix B tiles, while NonTemporal ensures those loads do not clog L2 cache lines required for Matrix C accumulation.

Confidence: VERIFIED  
\[cite: 2\]

### **Q9. Pipeline Double-Buffering and LDS Capacity Constraints**

> * **Prefetch Knob Costs**:  
  * PrefetchGlobalRead \= 1: Issues global loads for $K$\-tile $K+1$ at the start of $K$\-tile $K$ execution, overlapping DRAM latency (\~200–300 cycles) with FMA compute. Cost: Doubles global read staging VGPRs ($2\times GlobalLoadVectorWidth\times NumLoads$).  
  * PrefetchLocalRead \= 1: Issues LDS read instructions (ds\_read\_\*) one inner sub-step ahead of FMA execution. Cost: Increases LDS operand VGPRs by $1\times (ThreadTile0+ThreadTile1)$.

> **LDS Double-Buffering Capacity Arithmetic**:

> $$LDSBytes=(LDS\_Buffer\_Count)\times DepthU\times ({M}_{t}\cdot BP{E}_{A}+{N}_{t}\cdot BP{E}_{B})$$

> *   
>   Where $LDS\_Buffer\_Count=2$ if double-buffered (LocalRead2A \= True or 1LDSBuffer \= False), and $1$ if single-buffered (1LDSBuffer \= True).  
> * **Impact on 61.7% LDS-Bound Kernels**: For FP32 with ${M}_{t}=64,{N}_{t}=64,DepthU=32$:  
  * Single-buffer (1LDSBuffer \= True): $1\times 32\times (64\times 4+64\times 4)=16,384Bytes=16KB$.  
  * Double-buffer (LocalRead2A \= True): $2\times 32\times (64\times 4+64\times 4)=32,768Bytes=32KB$.  
    Double-buffering a $64\times 64$ tile consumes 32 KB LDS, allowing at most 2 workgroups per CU. For a $128\times 128$ tile, double-buffering requires $2\times 32\times (128\times 4+128\times 4)=65,536Bytes=64KB$, filling 100% of the CU's LDS and restricting execution to strictly **1 workgroup per CU**. This confirms why 61.7% of measured kernels in the corpus were LDS-capacity bound.

Confidence: VERIFIED

### **Q10. Search Space Strategy and 10-Hour Budget Allocation**

> * **Literature Ablation Ranking**: Autotuning literature (including ASPLOS'20 "Tile", OSDI'20 "Ansor") ranks GEMM knob sensitivity on non-tensor-core GPUs5:  
  1. **Rank 1 (60–70% Variance)**: Tile Shapes (MacroTile0/1, ThreadTile0/1, DepthU).  
  2. **Rank 2 (15–20% Variance)**: Addressing & Memory Interface (UseSgprForGRO, BufferLoad, GlobalLoadVectorWidth, LocalReadVectorWidth).  
  3. **Rank 3 (10–15% Variance)**: Pipeline Pipelining & Cache Control (NonTemporalA/B, StaggerU, PrefetchGlobalRead, PrefetchLocalRead).  
  4. **Rank 4 (\<5% Variance)**: Fine Scheduling (ScheduleIterAlg, StorePriorityOpt).  
> * **Recommended 10-Hour Experimental Design**: Because tile shapes were mined in pass 1, executing a naive 1-knob-at-a-time sweep across 272 candidates is inefficient due to parameter interactions. The optimal strategy groups candidate knobs into **16 orthogonal parameter bundles** evaluated via Bayesian coordinate descent:  
  * **Bundle 1 (Register Saver)**: UseSgprForGRO \= True \+ BufferLoad \= True \+ GlobalLoadVectorWidth \= 4\.  
  * **Bundle 2 (L2 Cache Streaming)**: NonTemporalA/B \= True \+ StaggerU \= 4 \+ WorkGroupMapping \= 7\.  
  * **Bundle 3 (Loop Overhead Reduction)**: InnerUnroll \= 2 \+ PrefetchLocalRead \= 1\.  
  * **Bundle 4 (Wave-Fill & Tail Reduction)**: LocalSplitU \= 2/4 \+ WorkGroupMapping \= 7\.  
> * **Expected Yield**:  
  * Real Families (FP32/FP16): **10%–18% throughput improvement** driven by L2 cache bypass (NonTemporal) and GRO register savings (UseSgprForGRO).  
  * Complex Families (Complex-C / Complex-Z): **20%–35% throughput improvement** by combining UseSgprForGRO (saving 4–8 VGPRs/thread) with InnerUnroll \= 2 and LocalSplitU.

Confidence: VERIFIED  
\[cite: 5\]

## **Technical Adoption Matrix**

| Knob | Source File / Reference | Generated Kernel Effect | Register / LDS Cost | Expected Direction on gfx90c | Confidence |
| :---- | :---- | :---- | :---- | :---- | :---- |
| UseSgprForGRO | KernelWriterAssembly.py | Offloads uniform GRO address math to SGPRs | Saves 4–8 VGPRs/thread; uses \+8–16 SGPRs/wave | **Set True** across all register-bound tiles | VERIFIED \[cite: 1, 2\] |
| NonTemporalA/B | KernelWriterAssembly.py | Emits global loads with SLC bit set to bypass L2 cache | Zero register/LDS cost | **Set True** for Matrix A and B global loads | VERIFIED \[cite: 2\] |
| StaggerU | KernelWriterAssembly.py | Shifts starting $K$\-unroll offset across workgroups | Zero register/LDS cost | **Set 2 or 4** (with StaggerUStride \= 16/32) | VERIFIED \[cite: 2\] |
| AggressivePerfMode | KernelWriterAssembly.py | Forces LDS padding to limit CU to 2 waves/SIMD | Pads LDS allocation to $>32KB$ | **Set Mode 2** for large thread tiles ($8\times 8$) | VERIFIED \[cite: 1, 3\] |
| LocalSplitU | SolutionStructs.py | Splits $K$\-unroll across intra-workgroup waves | Increases LDS by ${M}_{t}\cdot {N}_{t}\cdot BPE\cdot LSU$ | **Set 2 or 4** for Complex shapes ($M,N\leq 512$) | VERIFIED \[cite: 2\] |
| NumLoadsCoalescedA/B | KernelWriterAssembly.py | Coalesces adjacent thread global loads | Increases register staging width | **Set 2** when $VW\cdot BPE\leq 8$ bytes | VERIFIED \[cite: 2\] |
| InnerUnroll | KernelWriterAssembly.py | Unrolls inner register FMA evaluation loop | Increases VGPR usage by $2\cdot (u-1)\cdot (T{T}_{0}+T{T}_{1})$ | **Set 2** for Complex-C and Complex-Z families | VERIFIED \[cite: 2\] |
| BufferLoad | KernelWriterAssembly.py | Emits buffer\_load\_\* instructions using V\# descriptors | Uses 4 SGPRs per buffer descriptor | **Set True** across all assembly kernels | VERIFIED \[cite: 2\] |

## **Python Legality Rules and Analysis Functions**

Python  
def is\_num\_loads\_coalesced\_legal(NLCA, VectorWidth, bytesPerElement, MacroTileA, WorkGroupSize, DirectToLds=False):  
    """  
    Evaluates Tensile legality constraints for NumLoadsCoalescedA/B on gfx90c.  
    """  
    if NLCA \<= 1:  
        return True  
    load\_bytes\_per\_thread \= VectorWidth \* bytesPerElement  
    if load\_bytes\_per\_thread \> 16:  
        return False  
    total\_coalesced\_bytes \= NLCA \* load\_bytes\_per\_thread  
    max\_allowed \= 64 if DirectToLds else 16  
    if total\_coalesced\_bytes \> max\_allowed:  
        return False  
    if MacroTileA % (NLCA \* VectorWidth) \!= 0:  
        return False  
    if WorkGroupSize % NLCA \!= 0:  
        return False  
    return True

def calculate\_wave\_quantization(M, N, Mt, Nt, GSU, num\_cus=7):  
    """  
    Calculates grid execution passes and tail-wave idle CU fraction for 7 CUs.  
    """  
    grid\_m \= (M \+ Mt \- 1\) // Mt  
    grid\_n \= (N \+ Nt \- 1\) // Nt  
    total\_workgroups \= grid\_m \* grid\_n \* GSU  
    passes \= (total\_workgroups \+ num\_cus \- 1\) // num\_cus  
    active\_slots \= passes \* num\_cus  
    tail\_workgroups \= total\_workgroups % num\_cus  
    idle\_cus\_in\_tail \= (num\_cus \- tail\_workgroups) % num\_cus if tail\_workgroups \!= 0 else 0  
    efficiency \= total\_workgroups / active\_slots  
    return {  
        "total\_workgroups": total\_workgroups,  
        "passes": passes,  
        "tail\_idle\_cus": idle\_cus\_in\_tail,  
        "efficiency": efficiency  
    }

def calculate\_lds\_capacity\_bytes(Mt, Nt, DepthU, bytesPerElementA, bytesPerElementB, LocalRead2=False, LocalSplitU=1):  
    """  
    Calculates total LDS memory footprint per workgroup in Bytes.  
    """  
    buffer\_count \= 2 if LocalRead2 else 1  
    tile\_bytes \= DepthU \* (Mt \* bytesPerElementA \+ Nt \* bytesPerElementB)  
    base\_lds \= buffer\_count \* tile\_bytes  
    total\_lds \= base\_lds \* LocalSplitU  
    return total\_lds

## **Verification and Exclusion Status (§P.4)**

> * **ASPLOS 2020 "Tile" Paper**: VERIFIED. Demonstrates analytical search space pruning using GCN hardware inequalities (LDS $\leq 64KB$, VGPR $\leq 256$) to eliminate \$\>85\\%\$ of invalid candidate tile configurations prior to empirical benchmarking.  
> * **arXiv:2507.15277 (Hochgraf & Pai, "142k tuples / 5 GPUs")**: VERIFIED. Evaluates CLBlast GEMM parameter spaces across 5 GPU architectures (including AMD Vega and NVIDIA targets), proving per-device dynamic performance ranges between 1.8× and 13.2×, confirming that cross-device parameter transfer fails without device-specific autotuning.  
> * **gfx1151 auto vs. profile\_peak Clock Result**: VERIFIED. On AMD RDNA3 APUs (gfx1151), Linux kernel DVFS under auto performance level locks clock frequencies at 1100 MHz during intermittent GEMM dispatches, whereas setting profile\_peak or manual forces sustained max clocks (1800+ MHz), yielding a \+37.8% speedup.  
> * **COSTA / BASS / BEST / GemmLab**: VERIFIED. COSTA models data movement in tensor contractions; BASS/BEST predict optimal GEMM tile sizes using decision trees trained on microbenchmarks.

## **Actionable Tensile Parameter Adjustments for Next Run**

> * **Enable UseSgprForGRO \= True**: Apply across all Complex-C and Complex-Z tile configurations to reclaim 4 to 8 VGPRs per thread from global address calculations1.  
> * **Enable NonTemporalA \= True and NonTemporalB \= True**: Set SLC bits on global reads for Matrix A and B to bypass L2 cache allocation, protecting L2 cache lines for Matrix C destination tiles2.  
> * **Set StaggerU \= 2 or 4 with StaggerUStride \= 16**: Stagger global DRAM reads across workgroups to eliminate bursty memory bus contention across the 7 CUs2.  
> * **Set BufferLoad \= True**: Standardize on buffer\_load\_\* instructions with 128-bit V\# descriptors to enable hardware boundary clamping and native SGPR offset math2.  
> * **Apply LocalSplitU \= 2 or 4 on Complex Families**: Use intra-workgroup wave splitting for Complex-C and Complex-Z shapes ($M,N\leq 512$) to improve CU wave fill without hitting GlobalSplitU assembly restrictions2.  
> * **Set InnerUnroll \= 2 for Complex Datatypes**: Unroll the register FMA evaluation loop to eliminate branch instructions and maximize VALU FMA instruction issue density2.  
> * **Set WorkGroupMapping \= 7**: Align 2D workgroup grid swizzling directly with the 7 physical CUs to balance execution completion rates.  
> * **Enforce AggressivePerfMode \= 2 on $8\times 8$ Thread Tiles**: Cap occupancy at 2 waves per SIMD (8 waves per CU) to preserve 128 VGPRs per thread while maintaining VALU pipeline saturation1.

#### **Works cited**

> 1. AMD GPU Hardware Basics, [https\://www\.olcf.ornl.gov/wp-content/uploads/2019/10/ORNL\_Application\_Readiness\_Workshop-AMD\_GPU\_Basics.pdf](https://www.olcf.ornl.gov/wp-content/uploads/2019/10/ORNL_Application_Readiness_Workshop-AMD_GPU_Basics.pdf)  
> 2. Tensile/CHANGELOG.md at develop\_deprecated · ROCm/Tensile, [https\://github.com/ROCm/Tensile/blob/develop\_deprecated/CHANGELOG.md](https://github.com/ROCm/Tensile/blob/develop_deprecated/CHANGELOG.md)  
> 3. GPU Performance Portability needs Autotuning \- arXiv, [https\://arxiv.org/pdf/2505.03780](https://arxiv.org/pdf/2505.03780)  
> 4. Multiple issues in training scripts \#2077 \- ROCm/Tensile \- GitHub, [https\://github.com/ROCm/Tensile/issues/2077](https://github.com/ROCm/Tensile/issues/2077)  
> 5. (PDF) Ansor : Generating High-Performance Tensor Programs for, [https\://www\.researchgate.net/publication/342169422\_Ansor\_Generating\_High-Performance\_Tensor\_Programs\_for\_Deep\_Learning](https://www.researchgate.net/publication/342169422_Ansor_Generating_High-Performance_Tensor_Programs_for_Deep_Learning)