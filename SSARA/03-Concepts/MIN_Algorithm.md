# MIN Algorithm (Belady's Optimal Replacement)

## Origin

The MIN algorithm was originally developed by Laszlo Belady in 1966 as an **optimal page replacement strategy** for operating systems. The key insight: when a cache/register set is full and a new item must be loaded, **evict the item whose next use is furthest in the future**.

This strategy is provably optimal for minimizing cache misses (or register spills) when future access patterns are known.

## Theoretical Foundation

**Optimality Theorem:** Given perfect knowledge of future accesses, evicting the item with the furthest next-use distance minimizes the total number of evictions.

**Practical Limitation:** In general programs, future accesses are unknown at compile time. However, for **straight-line code** (single basic block), the MIN algorithm achieves true optimality since the instruction sequence is fixed.

## Application to Register Allocation

In compiler register allocation, the MIN algorithm is adapted as follows:

### Algorithm (per basic block)

```
for each instruction I in forward order:
    1. Reload any operands not currently in registers
    2. If |active_registers| > limit:
         - Compute next-use distance for each active register
         - Spill the register with MAXIMUM next-use distance
    3. Add defined registers to active set
```

### Key Concepts

| Term | Definition |
|------|------------|
| **Next-Use Distance (NUD)** | Number of instructions until the next use of a register |
| **Active Set** | Registers currently "live" and occupying physical registers |
| **Spill** | Store register to memory (stack slot) |
| **Reload** | Load register from memory before use |

## Extension to CFGs (Braun & Hack, CC 2009)

The paper ["Register Spilling and Live-Range Splitting for SSA-Form Programs"](https://pp.ipd.kit.edu/uploads/publikationen/braun09cc.pdf) by Matthias Braun and Sebastian Hack extends the MIN algorithm to **control flow graphs** in SSA form:

### Challenges in CFGs

1. **Multiple paths**: Next-use distance depends on which branch is taken
2. **Φ-functions**: SSA merges create implicit uses at join points
3. **Loop back-edges**: Variables may be "used" infinitely far in the future on non-loop paths but immediately on loop paths

### Solutions from Braun09

1. **Conservative next-use**: Take minimum distance across all paths
2. **Φ-function handling**: Treat Φ inputs as uses at the end of predecessor blocks
3. **Loop-awareness**: Special handling for back-edges to avoid pathological spilling

## SSA Spiller Implementation

In the AMDGPU SSA Spiller, the MIN algorithm is implemented via:

### NextUseAnalysis Pass

- **Source**: [`AMDGPUNextUseAnalysis.cpp`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.cpp)
- **Upstream PR**: [#156079](https://github.com/llvm/llvm-project/pull/156079)

Key APIs:
- [`getNextUseDistance()`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.cpp#L180-L210) - Returns distance to next use
- [`getSortedSubregUses()`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.cpp#L253-L303) - Orders subregisters by next-use (furthest first)

### Spill Selection

In [`getVMPsToSpill()`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp#L511-L621):

1. Sort active registers by next-use distance (descending)
2. Select registers with furthest use until RP budget is met
3. For large registers, use lane-level ordering via `getSortedSubregUses()`

## Limitations

### Static Analysis Limitation

NextUseAnalysis runs **before** spilling. Registers created by reloads/PHIs have no NUA entries. See [Static NUA Limitation](../08-Worklog/issues/Next_Use_Analysis/Static_NUA_limitation.md).

### CFG Complexity

MIN optimality only holds for straight-line code. In CFGs with divergent control flow, spill placement interacts with EXEC mask correctness, requiring additional constraints beyond pure Belady heuristics.

## References

1. Belady, L.A. (1966). "A Study of Replacement Algorithms for Virtual Storage Computers"
2. Braun, M. & Hack, S. (2009). ["Register Spilling and Live-Range Splitting for SSA-Form Programs"](https://pp.ipd.kit.edu/uploads/publikationen/braun09cc.pdf), CC 2009
3. Local copy: [`braun09cc_1_1.pdf`](../06-Research/Papers/braun09cc_1_1.pdf)

## Used By

- [SSA Spiller](../04-Design/SSA_SPILLER_DESIGN.md) - Spill candidate selection
- [NextUseAnalysis](../02-Components/NextUseAnalysis.md) - Distance computation
